"""Search entry node — seed the RAG query from the user's message.

Entered when route decides "search". Seeds the user message as the query and
resets per-search working fields before the RAG pipeline (intent → … → format).
"""
from maru_lang.graph.rag.state import RagState


def make_search_entry_node():
    """Seed `query` from the user message and reset per-search fields."""

    async def search_entry_node(state: RagState) -> dict:
        messages = state.get("messages", [])
        query = messages[-1].content if messages else ""
        return {
            "query": query,
            "rewritten_query": "",
            "keywords": [],
            "documents": [],
            "result": "",
            "retry_count": 0,
            "evaluation": "",
            "excluded_doc_ids": [],
        }

    return search_entry_node
