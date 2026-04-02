"""Chat graph state schema."""
from typing import Annotated, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class ChatState(TypedDict):
    """Shared state for the ReAct chat agent.

    Attributes:
        messages: Conversation history (auto-accumulated via add_messages reducer).
        team_ids: Team IDs for access control.
        team_names: Team name list.
        accessible_groups: Document groups the user can access.
        retrieved_documents: Documents retrieved via RAG.
    """
    messages: Annotated[list[BaseMessage], add_messages]
    team_ids: list[int]
    team_names: list[str]
    accessible_groups: list[str]
    retrieved_documents: list[dict]
