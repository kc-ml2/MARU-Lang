"""Search plumbing nodes — bridge the agent's tool_call to the RAG pipeline.

`search_entry` reads the agent's knowledge_search tool_call, seeds the query and
resets per-search fields, then the RAG chain runs. `search_result` turns the
formatted result back into a ToolMessage and surfaces retrieved_documents.
"""
from langchain_core.messages import ToolMessage

from maru_lang.graph.rag.state import RagState

TOOL_NAME = "knowledge_search"


def _find_tool_call(message) -> dict | None:
    """Return the knowledge_search tool_call from an AI message, if present."""
    tool_calls = getattr(message, "tool_calls", None) or []
    for call in tool_calls:
        if call.get("name") == TOOL_NAME:
            return call
    return tool_calls[0] if tool_calls else None


def make_search_entry_node():
    """Extract the search query/tool_call_id and reset per-search rag fields."""

    async def search_entry_node(state: RagState) -> dict:
        messages = state.get("messages", [])
        call = _find_tool_call(messages[-1]) if messages else None
        query = (call.get("args", {}) or {}).get("query", "") if call else ""
        tool_call_id = call.get("id") if call else None

        # Reset per-search working fields (these have no reducer; see state.py).
        return {
            "query": query,
            "tool_call_id": tool_call_id,
            "rewritten_query": "",
            "keywords": [],
            "documents": [],
            "result": "",
            "retry_count": 0,
            "evaluation": "",
            "excluded_doc_ids": [],
            "rag_log": [],
        }

    return search_entry_node


def make_search_result_node():
    """Append the RAG result as a ToolMessage and surface retrieved_documents."""

    async def search_result_node(state: RagState) -> dict:
        result = state.get("result", "")
        tool_call_id = state.get("tool_call_id")

        documents = [
            {
                "document_id": doc.metadata.get("document_id", "unknown"),
                "document_name": doc.metadata.get("document_name", ""),
                "score": doc.metadata.get("score", 0),
                "content": doc.page_content,
                "file_path": doc.metadata.get("file_path", ""),
                "group_id": doc.metadata.get("group_id"),
            }
            for doc in state.get("documents", [])
        ]

        tool_message = ToolMessage(
            content=result,
            tool_call_id=tool_call_id,
            name=TOOL_NAME,
        )

        return {
            "messages": [tool_message],
            "retrieved_documents": documents,
        }

    return search_result_node
