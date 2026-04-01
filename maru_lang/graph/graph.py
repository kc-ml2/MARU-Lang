"""LangGraph ReAct 그래프 정의 및 컴파일"""
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from maru_lang.graph.state import ChatState
from maru_lang.graph.nodes import make_agent_node
from maru_lang.graph.tools import knowledge_search, memory_read, memory_write

ALL_TOOLS = [knowledge_search, memory_read, memory_write]


def _should_continue(state: ChatState) -> str:
    """agent 응답에 tool_calls가 있으면 tools로, 없으면 END"""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


def create_graph(
    model: BaseChatModel,
    checkpointer=None,
    tools: list | None = None,
):
    """ReAct 패턴의 LangGraph 생성

    Args:
        model: LangChain ChatModel (OpenAI, Anthropic 등)
        checkpointer: 체크포인터 (None이면 MemorySaver 사용)
        tools: 사용할 tool 목록 (None이면 기본 ALL_TOOLS)

    Returns:
        컴파일된 StateGraph
    """
    if tools is None:
        tools = ALL_TOOLS

    if checkpointer is None:
        checkpointer = MemorySaver()

    # LLM에 tool 바인딩
    model_with_tools = model.bind_tools(tools)

    # 그래프 구성
    graph = StateGraph(ChatState)

    # 노드 추가
    graph.add_node("agent", make_agent_node(model_with_tools))
    graph.add_node("tools", ToolNode(tools))

    # 엣지 연결
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", _should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")  # tool 결과를 다시 agent로

    return graph.compile(checkpointer=checkpointer)
