"""knowledge_search tool factory with intent + keyword preprocessing."""
import logging
from typing import Annotated, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.retrievers import BaseRetriever
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from maru_lang.graph.chat.retriever import VectorRetriever
from maru_lang.graph.chat.tools.intent import extract_intent
from maru_lang.graph.chat.tools.keywords import extract_keywords

logger = logging.getLogger(__name__)


def create_knowledge_search_tool(
    retriever: BaseRetriever,
    llm: Optional[BaseChatModel] = None,
):
    """Create a knowledge_search tool with optional intent/keyword preprocessing.

    Args:
        retriever: A BaseRetriever (plain or CompressedRetriever).
        llm: LLM for intent rewriting and keyword extraction. If None, skips preprocessing.

    Returns:
        A @tool-decorated async function.
    """

    @tool
    async def knowledge_search(
        query: str,
        state: Annotated[dict, InjectedState] = None,
    ) -> str:
        """Search team documents for relevant information.
        Use this tool to find internal documents when answering user questions.

        Args:
            query: Search query or keywords.
        """
        try:
            team_ids: list[int] = state.get("team_ids", []) if state else []

            # Inject team_ids into the base retriever
            base = retriever
            if hasattr(base, "base_retriever"):
                base = base.base_retriever
            if isinstance(base, VectorRetriever):
                base.team_ids = team_ids

            # Preprocess query with LLM if available
            search_query = query
            if llm is not None:
                rewritten = await extract_intent(query, llm)
                keywords = await extract_keywords(rewritten, llm)
                if keywords:
                    search_query = " ".join(keywords)
                    logger.info(f"Query: {query} → Keywords: {search_query}")

            docs = await retriever.ainvoke(search_query)

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
