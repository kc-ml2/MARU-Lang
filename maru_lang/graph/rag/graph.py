"""Chat graph: memory-aware RAG with an explicit search/no-search router.

Instead of a ReAct tool-calling agent, a `route` node classifies whether the
question needs document search. Memory (user facts/preferences + prior session
turns) is loaded up front and written back at the end, so the graph is the
single owner of conversational memory.

Topology
--------
    context_builder            # load memory (UserMemory + session) into state
        │
        ▼
      route ──"direct"──────────────────────────────────┐
        │ "search"                                       │
        ▼                                                │
    search_entry → intent → keywords → retrieve → evaluate
                                          ▲          │
                                          └──"retry"─┘ (regenerate keywords)
                                                     │ "rerank"
                                          rerank → format ──────────────► generate
                                                                             │
                          (function == "feedback") ──"score"── score ──"reason"── reason
                                                       │ else                 │
                                                       └──────────────────────┤
                                                                              ▼
                                              summarize → memory_extractor → END
                                          (turn/session summary)  (persist user memory)

Config and the LLM are read internally; callers just call create_rag_graph().
Conversation/memory persistence happens inside the graph (summarize +
memory_extractor), gated on session_id/user_id being present in the state.
"""
from typing import AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END
from langgraph.types import Command

from maru_lang.configs import get_config
from maru_lang.core.llm import get_model_with_fallbacks
from maru_lang.graph.rag.state import RagState, build_input
from maru_lang.graph.rag.retriever import build_retriever
from maru_lang.graph.rag.reranker import build_compressor
from maru_lang.graph.rag.nodes import (
    # entry / memory
    make_context_builder_node,
    # routing
    make_route_node,
    route_decision,
    # RAG pipeline
    make_search_entry_node,
    make_intent_node,
    make_keyword_node,
    make_retrieve_node,
    make_evaluate_node,
    evaluate_route,
    make_rerank_node,
    format_node,
    # answer
    make_generate_node,
    # feedback
    feedback_route,
    score_node,
    score_route,
    make_reason_node,
    # terminal persistence (write-back)
    make_summarize_node,
    make_memory_extractor_node,
)


# The node that produces the user-facing answer. Only its LLM tokens are
# streamed to the client (all other nodes call the LLM internally).
_ANSWER_NODE = "generate"


def create_rag_graph(
    model: BaseChatModel | None = None,
    checkpointer=None,
):
    """Build and compile the chat graph.

    Reads config and the LLM internally; all settings have sensible defaults.

    Args:
        model: LangChain ChatModel. If None, auto-loads from config with fallbacks.
        checkpointer: Checkpointer instance (defaults to MemorySaver).

    Returns:
        Compiled StateGraph.

    Raises:
        RuntimeError: If no LLM model is available.
    """
    if model is None:
        model = get_model_with_fallbacks()
        if model is None:
            raise RuntimeError("No LLM model available. Check llms config.")

    cfg = get_config()
    retriever = build_retriever(cfg)
    compressor = build_compressor(cfg)

    graph = StateGraph(RagState)

    # --- Nodes -----------------------------------------------------------
    # Memory (read) + routing + answer
    graph.add_node("context_builder", make_context_builder_node(cfg.memory_recent_turns))
    graph.add_node("route", make_route_node(model))
    graph.add_node("generate", make_generate_node(model, system_prompt=cfg.system_prompt))

    # RAG retrieval pipeline
    graph.add_node("search_entry", make_search_entry_node())
    graph.add_node("intent", make_intent_node(model))
    graph.add_node("keywords", make_keyword_node(model))
    graph.add_node("retrieve", make_retrieve_node(retriever))
    graph.add_node("evaluate", make_evaluate_node(
        method=cfg.evaluate_method,
        llm=model if cfg.evaluate_method == "llm" else None,
    ))
    graph.add_node("rerank", make_rerank_node(compressor))
    graph.add_node("format", format_node)

    # Optional feedback collection (interrupt/resume)
    graph.add_node("score", score_node)
    graph.add_node("reason", make_reason_node(model))

    # Terminal write-back: conversation summary + user persistent memory
    graph.add_node("summarize", make_summarize_node(model))
    graph.add_node("memory_extractor", make_memory_extractor_node(model))

    # --- Edges (in flow order) ------------------------------------------
    # Entry: load memory, then decide search vs. direct answer.
    graph.set_entry_point("context_builder")
    graph.add_edge("context_builder", "route")
    graph.add_conditional_edges(
        "route", route_decision,
        {"search_entry": "search_entry", "generate": "generate"},
    )

    # Search path: retrieve → evaluate (retry loop) → rerank → format → answer.
    graph.add_edge("search_entry", "intent")
    graph.add_edge("intent", "keywords")
    graph.add_edge("keywords", "retrieve")
    graph.add_edge("retrieve", "evaluate")
    graph.add_conditional_edges(
        "evaluate", evaluate_route,
        {"rerank": "rerank", "retry": "keywords"},
    )
    graph.add_edge("rerank", "format")
    graph.add_edge("format", "generate")

    # After the answer: optional feedback, then converge on the write-back tail.
    graph.add_conditional_edges(
        "generate", feedback_route,
        {"score": "score", "summarize": "summarize"},
    )
    graph.add_conditional_edges(
        "score", score_route,
        {"reason": "reason", "summarize": "summarize"},
    )
    graph.add_edge("reason", "summarize")

    # Write-back tail (terminal): summarize the turn/session, then persist any
    # durable user facts/preferences. Both no-op without session_id/user_id.
    graph.add_edge("summarize", "memory_extractor")
    graph.add_edge("memory_extractor", END)

    if checkpointer is None:
        checkpointer = MemorySaver()

    return graph.compile(checkpointer=checkpointer)


async def run_rag(
    message: str,
    team_ids: list[int],
    team_names: list[str],
    *,
    graph,
    config: dict | None = None,
    function: str | None = None,
    session_id: str | None = None,
    user_id: int | None = None,
) -> str:
    """Run the graph once and return the final answer text."""
    input_state = build_input(
        message, team_ids, team_names,
        function=function, session_id=session_id, user_id=user_id,
    )
    result = await graph.ainvoke(input_state, config=config)
    return result["messages"][-1].content


async def stream_rag(
    message,
    team_ids: list[int],
    team_names: list[str],
    *,
    graph,
    config: dict | None = None,
    function: str | None = None,
    session_id: str | None = None,
    user_id: int | None = None,
) -> AsyncIterator[tuple[str, str | list]]:
    """Stream the graph execution as (event_type, content) tuples.

    Events:
        - ("token", str): a user-facing answer token (from the answer node only).
        - ("retrieve", list[dict]): retrieved document metadata.
        - ("interrupt", value): graph paused (feedback), awaiting a resume.

    Args:
        message: a user message string, or Command(resume=value) to resume.
    """
    if isinstance(message, Command):
        input_state = message
    else:
        input_state = build_input(
            message, team_ids, team_names,
            function=function, session_id=session_id, user_id=user_id,
        )

    async for mode, event in graph.astream(
        input_state,
        config=config,
        stream_mode=["messages", "updates"],
    ):
        if mode == "messages":
            msg, metadata = event
            # Stream only the answer node's tokens. Other nodes (route, intent,
            # keywords, evaluate, rerank, summary, memory) also call the LLM, but
            # their output must not leak into the user-visible stream.
            if metadata.get("langgraph_node") != _ANSWER_NODE:
                continue
            if isinstance(msg, AIMessageChunk) and msg.content:
                yield "token", msg.content
        elif mode == "updates":
            for _node_name, state_update in event.items():
                if not isinstance(state_update, dict):
                    continue
                docs = state_update.get("retrieved_documents")
                if docs:
                    yield "retrieve", docs

    # After streaming, surface a pending interrupt (if the turn paused for feedback).
    snapshot = await graph.aget_state(config)
    for task in snapshot.tasks:
        if task.interrupts:
            yield "interrupt", task.interrupts[0].value
            break
