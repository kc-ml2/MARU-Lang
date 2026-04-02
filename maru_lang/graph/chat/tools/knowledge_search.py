"""knowledge_search tool — invokes the RAG graph."""
import logging
from typing import Annotated, Optional

from langchain_core.documents.compressor import BaseDocumentCompressor
from langchain_core.language_models import BaseChatModel
from langchain_core.retrievers import BaseRetriever
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from maru_lang.graph.rag import run_rag

logger = logging.getLogger(__name__)


def create_knowledge_search_tool(
    retriever: BaseRetriever,
    llm: Optional[BaseChatModel] = None,
    compressor: Optional[BaseDocumentCompressor] = None,
    evaluate_method: str = "rule",
):
    """Create a knowledge_search tool that runs the RAG graph.

    Args:
        retriever: BaseRetriever for document search.
        llm: LLM for intent/keyword extraction.
        compressor: Optional reranker (passed to RAG graph).

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

            if llm is not None:
                return await run_rag(
                    query=query,
                    team_ids=team_ids,
                    retriever=retriever,
                    llm=llm,
                    compressor=compressor,
                    evaluate_method=evaluate_method,
                )
            else:
                # Fallback: direct retriever call without RAG graph
                from maru_lang.graph.rag.retriever import VectorRetriever
                if isinstance(retriever, VectorRetriever):
                    retriever.team_ids = team_ids

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
