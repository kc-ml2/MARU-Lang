"""knowledge_search tool — invokes the RAG graph."""
import json
import logging
from typing import Annotated

from langchain_core.documents.compressor import BaseDocumentCompressor
from langchain_core.language_models import BaseChatModel
from langchain_core.retrievers import BaseRetriever
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from maru_lang.constants import RETRIEVED_DOCS_TAG
from maru_lang.graph.rag import run_rag

logger = logging.getLogger(__name__)


def create_knowledge_search_tool(
    retriever: BaseRetriever,
    llm: BaseChatModel,
    compressor: BaseDocumentCompressor | None = None,
    evaluate_method: str = "rule",
):
    """Create a knowledge_search tool that runs the RAG graph.

    Args:
        retriever: BaseRetriever for document search.
        llm: LLM for intent/keyword extraction (required).
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

            rag_result = await run_rag(
                query=query,
                team_ids=team_ids,
                retriever=retriever,
                llm=llm,
                compressor=compressor,
                evaluate_method=evaluate_method,
            )

            # Embed documents metadata as JSON trailer for state extraction
            docs_json = json.dumps(rag_result["documents"], ensure_ascii=False)
            return f'{rag_result["result"]}\n\n<!-- {RETRIEVED_DOCS_TAG}:{docs_json} -->'

        except Exception as e:
            logger.error(f"knowledge_search failed: {e}")
            return f"Search error: {e}"

    return knowledge_search
