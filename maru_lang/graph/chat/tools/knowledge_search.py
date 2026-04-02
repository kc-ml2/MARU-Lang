"""knowledge_search tool factory.

Receives a pre-built retriever (with or without reranking already composed).
No config or reranker logic inside — just invoke and format.
"""
import logging
from typing import Annotated

from langchain_core.retrievers import BaseRetriever
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from maru_lang.graph.chat.retriever import VectorRetriever

logger = logging.getLogger(__name__)


def create_knowledge_search_tool(retriever: BaseRetriever):
    """Create a knowledge_search tool bound to the given retriever.

    Args:
        retriever: A BaseRetriever (plain or ContextualCompressionRetriever).

    Returns:
        A @tool-decorated async function.
    """

    @tool
    async def knowledge_search(
        query: str,
        search_method: str = "hybrid",
        state: Annotated[dict, InjectedState] = None,
    ) -> str:
        """Search team documents for relevant information.
        Use this tool to find internal documents when answering user questions.

        Args:
            query: Search query or keywords.
            search_method: Search method ("vector" or "hybrid"). Defaults to "hybrid".
        """
        try:
            # Inject team_ids from ChatState into the retriever
            team_ids: list[int] = state.get("team_ids", []) if state else []

            # Set team_ids on the base retriever
            base = retriever
            if hasattr(base, "base_retriever"):
                # CompressedRetriever wraps the real retriever
                base = base.base_retriever
            if isinstance(base, VectorRetriever):
                base.team_ids = team_ids
                base.search_method = search_method

            docs = await retriever.ainvoke(query)

            if not docs:
                return f"No documents found for '{query}'."

            formatted = []
            for doc in docs:
                doc_id = doc.metadata.get("document_id", "unknown")
                doc_name = doc.metadata.get("document_name", "")
                score = doc.metadata.get("score", 0)
                formatted.append(
                    f"[{doc_id}] {doc_name} (score: {score:.2f})\n"
                    f"{doc.page_content}"
                )
            return "\n\n---\n\n".join(formatted)

        except Exception as e:
            logger.error(f"knowledge_search failed: {e}")
            return f"Search error: {e}"

    return knowledge_search
