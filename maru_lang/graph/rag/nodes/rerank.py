"""Rerank node — apply compressor/reranker to retrieved documents."""
from typing import Optional
from langchain_core.documents.compressor import BaseDocumentCompressor
from maru_lang.graph.rag.state import RagState


def make_rerank_node(compressor: Optional[BaseDocumentCompressor]):
    """Create a rerank node. If no compressor, passes documents through."""

    async def rerank_node(state: RagState) -> dict:
        docs = state["documents"]

        if compressor is not None and docs:
            query = state["rewritten_query"] or state["query"]
            docs = list(compressor.compress_documents(docs, query))
            return {
                "documents": docs,
                "messages": [f"Reranked: {len(docs)} documents"],
            }

        return {"messages": ["Rerank skipped (no compressor)"]}

    return rerank_node
