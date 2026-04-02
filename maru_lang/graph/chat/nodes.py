"""Chat graph nodes - agent node definition."""
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage

from maru_lang.constants import SYSTEM_PROMPT
from maru_lang.graph.chat.state import ChatState


def make_agent_node(model: BaseChatModel):
    """Agent node factory - returns a node function bound to the given model."""

    async def agent_node(state: ChatState) -> dict:
        messages = state["messages"]

        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)

        response = await model.ainvoke(messages)
        return {"messages": [response]}

    return agent_node
