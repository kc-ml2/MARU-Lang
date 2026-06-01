"""Agent node — the ReAct decision/answer node.

The model is bound with the knowledge_search tool schema, so it either emits a
tool_call (→ search) or produces a final answer.
"""
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage

from maru_lang.constants import SYSTEM_PROMPT
from maru_lang.graph.rag.state import RagState


def make_agent_node(model: BaseChatModel, system_prompt: str = ""):
    """Agent node factory.

    Args:
        model: LangChain ChatModel (already bound with tools).
        system_prompt: Custom system prompt. Falls back to SYSTEM_PROMPT if empty.
    """
    prompt = system_prompt or SYSTEM_PROMPT

    async def agent_node(state: RagState) -> dict:
        messages = state["messages"]

        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=prompt)] + list(messages)

        response = await model.ainvoke(messages)
        return {"messages": [response]}

    return agent_node
