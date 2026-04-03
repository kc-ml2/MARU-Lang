"""Chat graph nodes - agent node and tools node."""
import json

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.prebuilt import ToolNode

from maru_lang.constants import SYSTEM_PROMPT, RETRIEVED_DOCS_PATTERN
from maru_lang.graph.chat.state import ChatState


def make_agent_node(model: BaseChatModel, system_prompt: str = ""):
    """Agent node factory.

    Args:
        model: LangChain ChatModel.
        system_prompt: Custom system prompt. Falls back to SYSTEM_PROMPT constant if empty.
    """
    prompt = system_prompt or SYSTEM_PROMPT

    async def agent_node(state: ChatState) -> dict:
        messages = state["messages"]

        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=prompt)] + list(messages)

        response = await model.ainvoke(messages)
        return {"messages": [response]}

    return agent_node


def make_tools_node(tools: list):
    """Create a tools node that extracts retrieved_documents from tool results.

    Wraps ToolNode and parses document metadata embedded by knowledge_search.
    """
    tool_node = ToolNode(tools)

    async def tools_node(state: ChatState) -> dict:
        result = await tool_node.ainvoke(state)

        # Extract document metadata from tool messages
        documents = []
        messages = result.get("messages", [])
        for msg in messages:
            if not isinstance(msg, ToolMessage):
                continue
            match = RETRIEVED_DOCS_PATTERN.search(msg.content or "")
            if match:
                try:
                    documents.extend(json.loads(match.group(1)))
                except (json.JSONDecodeError, TypeError):
                    pass
                # Strip the metadata trailer from the message content
                msg.content = RETRIEVED_DOCS_PATTERN.sub("", msg.content).rstrip()

        update = {"messages": messages}
        if documents:
            update["retrieved_documents"] = documents
        return update

    return tools_node
