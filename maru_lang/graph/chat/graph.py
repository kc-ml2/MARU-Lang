"""LangGraph ReAct chat graph definition and execution.

Config is read internally at graph creation time.
Callers just call create_chat_graph() — config and LLM loaded internally.
"""
from typing import AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, AIMessageChunk
from langchain_core.retrievers import BaseRetriever
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from maru_lang.configs import get_config
from maru_lang.graph.llm import get_model_with_fallbacks
from maru_lang.graph.chat.state import ChatState
from maru_lang.graph.chat.nodes import make_agent_node
from maru_lang.configs.models import MaruConfig
from maru_lang.graph.llm.client import create_chat_model
from maru_lang.graph.chat.retriever import VectorRetriever, CompressedRetriever
from maru_lang.graph.chat.reranker import CrossEncoderCompressor, LLMReranker
from maru_lang.graph.chat.tools import create_knowledge_search_tool


def _should_continue(state: ChatState) -> str:
    """Route to tools node if tool_calls exist, otherwise END."""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


def _build_retriever(cfg: MaruConfig) -> BaseRetriever:
    """Build a retriever (optionally with reranking) from config.

    Supports two reranker types:
    - "cross_encoder": Uses a CrossEncoder model (e.g. BAAI/bge-reranker-v2-m3).
    - "llm": Uses an LLM from the llms config to score relevance.
    """
    base_retriever = VectorRetriever(
        top_k=cfg.retriever_top_k,
        search_method=cfg.retriever_search_method,
        embedding_model=cfg.embedding_model,
        embedding_device=cfg.embedding_device,
    )

    if not cfg.reranker_enabled:
        return base_retriever

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

        llm = create_chat_model(llm_config)
        compressor = LLMReranker(llm=llm, top_k=cfg.reranker_top_k or 3)
    else:
        # Default: cross_encoder
        compressor = CrossEncoderCompressor(
            model_name=cfg.reranker_model,
            top_k=cfg.reranker_top_k,
            device=cfg.reranker_device or cfg.embedding_device,
        )

    return CompressedRetriever(
        base_retriever=base_retriever,
        compressor=compressor,
    )


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
        retriever = _build_retriever(cfg)
        knowledge_search = create_knowledge_search_tool(retriever, llm=model)
        tools = [knowledge_search]

    if checkpointer is None:
        checkpointer = MemorySaver()

    model_with_tools = model.bind_tools(tools)

    graph = StateGraph(ChatState)
    graph.add_node("agent", make_agent_node(model_with_tools, system_prompt=cfg.system_prompt))
    graph.add_node("tools", ToolNode(tools))

    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", _should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile(checkpointer=checkpointer)


def _build_chat_input(
    message: str,
    team_ids: list[int],
    team_names: list[str],
    accessible_groups: list[str],
) -> dict:
    """Build the initial state dict for the chat graph."""
    return {
        "messages": [HumanMessage(content=message)],
        "team_ids": team_ids,
        "team_names": team_names,
        "accessible_groups": accessible_groups,
        "retrieved_documents": [],
    }


async def run_chat(
    message: str,
    team_ids: list[int],
    team_names: list[str],
    accessible_groups: list[str],
    *,
    graph,
    config: dict | None = None,
) -> str:
    """Run the chat graph and return a single response."""
    input_state = _build_chat_input(message, team_ids, team_names, accessible_groups)
    result = await graph.ainvoke(input_state, config=config)
    return result["messages"][-1].content


async def stream_chat(
    message: str,
    team_ids: list[int],
    team_names: list[str],
    accessible_groups: list[str],
    *,
    graph,
    config: dict | None = None,
) -> AsyncIterator[tuple[str, str]]:
    """Stream the chat graph execution.

    Yields:
        (event_type, content) tuples:
        - ("token", str): LLM token chunk.
        - ("tool_result", str): Tool call result.
    """
    input_state = _build_chat_input(message, team_ids, team_names, accessible_groups)

    async for event, metadata in graph.astream(
        input_state,
        config=config,
        stream_mode="messages",
    ):
        if isinstance(event, AIMessageChunk) and event.content:
            yield "token", event.content
        elif hasattr(event, "name") and event.name == "knowledge_search":
            yield "tool_result", event.content if hasattr(event, "content") else ""
