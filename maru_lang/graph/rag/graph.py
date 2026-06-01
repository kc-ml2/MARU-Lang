"""Unified RAG + ReAct agent graph.

A single compiled graph: the agent (ReAct) decides whether to search; if so,
control flows through the RAG pipeline nodes (intent → keywords → retrieve →
evaluate → rerank → format) and back to the agent as a ToolMessage. Optional
feedback (score → reason) runs after the final answer.

Config and LLM are read internally; callers just call create_rag_graph().
"""
from typing import AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, AIMessageChunk
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END
from langgraph.types import Command

from maru_lang.configs import get_config
from maru_lang.configs.models import MaruConfig
from maru_lang.core.llm import get_model_with_fallbacks
from maru_lang.core.llm.client import create_chat_model
from maru_lang.graph.rag.state import RagState
from maru_lang.graph.rag.tools import knowledge_search
from maru_lang.graph.rag.retriever import VectorRetriever
from maru_lang.graph.rag.reranker import CrossEncoderCompressor, LLMReranker
from maru_lang.graph.rag.nodes import (
    make_agent_node,
    make_intent_node,
    make_keyword_node,
    make_retrieve_node,
    make_evaluate_node,
    evaluate_route,
    make_rerank_node,
    format_node,
    make_search_entry_node,
    make_search_result_node,
    score_node,
    score_route,
    make_reason_node,
)


def _should_continue(state: RagState) -> str:
    """Route from agent: into search (tool_call), feedback score, or END."""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "search_entry"
    if state.get("function") == "feedback":
        return "score"
    return END


def _build_retriever_and_compressor(cfg: MaruConfig):
    """Build retriever and optional compressor from config.

    Returns:
        (retriever, compressor) tuple. compressor is None if reranking disabled.
    """
    retriever = VectorRetriever(
        top_k=cfg.retriever_top_k,
        search_method=cfg.retriever_search_method,
        embedding_model=cfg.embedding_model,
        embedding_device=cfg.embedding_device,
    )

    if not cfg.reranker_enabled:
        return retriever, None

    if cfg.reranker_type == "llm":
        llm_config = None
        for llm in cfg.llms:
            if cfg.reranker_llm and llm.name == cfg.reranker_llm:
                llm_config = llm
                break
        if llm_config is None and cfg.llms:
            llm_config = cfg.llms[0]
        if llm_config is None:
            raise RuntimeError("LLM reranker requires at least one LLM in config.")

        compressor = LLMReranker(llm=create_chat_model(llm_config), top_k=cfg.reranker_top_k or 3)
    else:
        compressor = CrossEncoderCompressor(
            model_name=cfg.reranker_model,
            top_k=cfg.reranker_top_k,
            device=cfg.reranker_device or cfg.embedding_device,
        )

    return retriever, compressor


def create_rag_graph(
    model: BaseChatModel | None = None,
    checkpointer=None,
    tools: list | None = None,
):
    """Create the unified RAG + ReAct agent graph.

    Reads config and LLM internally. All settings have sensible defaults.

    Args:
        model: LangChain ChatModel. If None, auto-loads from config with fallbacks.
        checkpointer: Checkpointer instance (defaults to MemorySaver).
        tools: Custom tool list for binding (overrides the default knowledge_search).

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
    retriever, compressor = _build_retriever_and_compressor(cfg)

    if tools is None:
        tools = [knowledge_search]
    model_with_tools = model.bind_tools(tools)

    graph = StateGraph(RagState)

    # Agent (ReAct) + feedback nodes
    graph.add_node("agent", make_agent_node(model_with_tools, system_prompt=cfg.system_prompt))
    graph.add_node("score", score_node)
    graph.add_node("reason", make_reason_node(model))

    # Search plumbing + RAG pipeline nodes
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
    graph.add_node("search_result", make_search_result_node())

    graph.set_entry_point("agent")
    graph.add_conditional_edges(
        "agent", _should_continue,
        {"search_entry": "search_entry", "score": "score", END: END},
    )

    # search_entry → RAG pipeline → search_result → back to agent (ReAct loop)
    graph.add_edge("search_entry", "intent")
    graph.add_edge("intent", "keywords")
    graph.add_edge("keywords", "retrieve")
    graph.add_edge("retrieve", "evaluate")
    graph.add_conditional_edges(
        "evaluate", evaluate_route,
        {"rerank": "rerank", "retry": "keywords"},
    )
    graph.add_edge("rerank", "format")
    graph.add_edge("format", "search_result")
    graph.add_edge("search_result", "agent")

    # Feedback branch
    graph.add_conditional_edges(
        "score", score_route,
        {"reason": "reason", END: END},
    )
    graph.add_edge("reason", END)

    if checkpointer is None:
        checkpointer = MemorySaver()

    return graph.compile(checkpointer=checkpointer)


def _build_input(
    message: str,
    team_ids: list[int],
    team_names: list[str],
    function: str | None = None,
) -> RagState:
    """Build the initial state dict for the graph."""
    return {
        "messages": [HumanMessage(content=message)],
        "team_ids": team_ids,
        "team_names": team_names,
        "function": function,
    }


async def run_rag(
    message: str,
    team_ids: list[int],
    team_names: list[str],
    *,
    graph,
    config: dict | None = None,
    function: str | None = None,
) -> str:
    """Run the graph and return a single response."""
    input_state = _build_input(message, team_ids, team_names, function=function)
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
) -> AsyncIterator[tuple[str, str | list]]:
    """Stream the graph execution.

    Yields:
        (event_type, content) tuples:
        - ("token", str): agent LLM token chunk (RAG-internal LLM tokens filtered out).
        - ("retrieve", list[dict]): Retrieved document metadata.
        - ("interrupt", value): Graph interrupted, awaiting resume.

    Args:
        message: User message string, or Command(resume=value) to resume.
    """
    if isinstance(message, Command):
        input_state = message
    else:
        input_state = _build_input(message, team_ids, team_names, function=function)

    async for mode, event in graph.astream(
        input_state,
        config=config,
        stream_mode=["messages", "updates"],
    ):
        if mode == "messages":
            msg, metadata = event
            # Only stream the user-facing agent tokens. The RAG pipeline nodes
            # (intent/keywords/evaluate/rerank) also call the LLM; their chunks
            # must NOT leak into the user stream.
            if metadata.get("langgraph_node") != "agent":
                continue
            if isinstance(msg, AIMessageChunk) and msg.content:
                yield "token", msg.content
        elif mode == "updates":
            for node_name, state_update in event.items():
                if not isinstance(state_update, dict):
                    continue
                docs = state_update.get("retrieved_documents")
                if docs:
                    yield "retrieve", docs

    # 스트리밍 종료 후 interrupt 여부 확인
    snapshot = await graph.aget_state(config)
    for task in snapshot.tasks:
        if task.interrupts:
            yield "interrupt", task.interrupts[0].value
            break
