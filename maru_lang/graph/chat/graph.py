"""LangGraph ReAct chat graph definition and execution.

Config is read internally at graph creation time.
Callers just call create_chat_graph() — config and LLM loaded internally.
"""
from typing import AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, AIMessageChunk
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END

from maru_lang.configs import get_config
from maru_lang.core.llm import get_model_with_fallbacks
from maru_lang.graph.chat.state import ChatState
from maru_lang.graph.chat.nodes import make_agent_node, make_tools_node
from maru_lang.configs.models import MaruConfig
from maru_lang.core.llm.client import create_chat_model
from maru_lang.graph.rag.retriever import VectorRetriever
from maru_lang.graph.rag.reranker import CrossEncoderCompressor, LLMReranker
from maru_lang.graph.chat.tools import create_knowledge_search_tool


def _should_continue(state: ChatState) -> str:
    """Route to tools node if tool_calls exist, otherwise END."""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
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


def create_chat_graph(
    model: BaseChatModel | None = None,
    checkpointer=None,
    tools: list | None = None,
):
    """Create a ReAct-pattern LangGraph for chat.

    Reads config and LLM internally. All settings have sensible defaults.

    Args:
        model: LangChain ChatModel. If None, auto-loads from config with fallbacks.
        checkpointer: Checkpointer instance (defaults to MemorySaver).
        tools: Custom tool list (overrides default tools).

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

    if tools is None:
        retriever, compressor = _build_retriever_and_compressor(cfg)
        knowledge_search = create_knowledge_search_tool(
            retriever, llm=model, compressor=compressor,
            evaluate_method=cfg.evaluate_method,
        )
        tools = [knowledge_search]

    if checkpointer is None:
        checkpointer = MemorySaver()

    model_with_tools = model.bind_tools(tools)

    graph = StateGraph(ChatState)
    graph.add_node("agent", make_agent_node(model_with_tools, system_prompt=cfg.system_prompt))
    graph.add_node("tools", make_tools_node(tools))

    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", _should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile(checkpointer=checkpointer)


def _build_chat_input(
    message: str,
    team_ids: list[int],
    team_names: list[str],
) -> ChatState:
    """Build the initial state dict for the chat graph."""
    return {
        "messages": [HumanMessage(content=message)],
        "team_ids": team_ids,
        "team_names": team_names,
    }


async def run_chat(
    message: str,
    team_ids: list[int],
    team_names: list[str],
    *,
    graph,
    config: dict | None = None,
) -> str:
    """Run the chat graph and return a single response."""
    input_state = _build_chat_input(message, team_ids, team_names)
    result = await graph.ainvoke(input_state, config=config)
    return result["messages"][-1].content


async def stream_chat(
    message: str,
    team_ids: list[int],
    team_names: list[str],
    *,
    graph,
    config: dict | None = None,
) -> AsyncIterator[tuple[str, str | list]]:
    """Stream the chat graph execution.

    Yields:
        (event_type, content) tuples:
        - ("token", str): LLM token chunk.
        - ("tool_result", str): Tool call result text.
        - ("retrieve", list[dict]): Retrieved document metadata.
    """
    input_state = _build_chat_input(message, team_ids, team_names)

    async for mode, event in graph.astream(
        input_state,
        config=config,
        stream_mode=["messages", "updates"],
    ):
        if mode == "messages":
            msg, metadata = event
            if isinstance(msg, AIMessageChunk) and msg.content:
                yield "token", msg.content
            elif hasattr(msg, "name") and msg.name == "knowledge_search":
                yield "tool_result", msg.content if hasattr(msg, "content") else ""
        elif mode == "updates":
            for node_name, state_update in event.items():
                docs = state_update.get("retrieved_documents")
                if docs:
                    yield "retrieve", docs
