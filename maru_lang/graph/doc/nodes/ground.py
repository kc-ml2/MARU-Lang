"""Ground node — retrieve internal team docs to ground the draft.

Reuses the RAG retrieval infrastructure (build_retriever/build_compressor) but
keeps DocState minimal by calling the retriever directly rather than reusing the
RAG node factories (which are bound to RagState working fields).
"""
import asyncio
from typing import Optional

from langchain_core.documents.compressor import BaseDocumentCompressor

from maru_lang.graph.doc.refs import base_ref, render_ref_context
from maru_lang.graph.doc.state import DocState
from maru_lang.graph.rag.retriever import VectorRetriever


def _to_chunk_dicts(docs) -> list[dict]:
    """Like rag format._to_doc_dicts but keeps the per-chunk vector id (doc.id)."""
    return [
        {
            **base_ref(doc, score_default=0),
            "file_path": doc.metadata.get("file_path", ""),
            "group_id": doc.metadata.get("group_id"),
        }
        for doc in docs
    ]


def make_ground_node(
    retriever: VectorRetriever,
    compressor: Optional[BaseDocumentCompressor],
):
    """Create a ground node bound to the given retriever/compressor."""

    async def ground_node(state: DocState) -> dict:
        team_ids = state.get("team_ids") or []
        instruction = state.get("instruction") or ""

        if not team_ids:
            return {"documents": [], "references": [], "context": ""}

        scoped = retriever.model_copy(update={"team_ids": team_ids})
        docs = await scoped.ainvoke(instruction)

        if compressor is not None and docs:
            docs = list(await asyncio.to_thread(
                compressor.compress_documents, docs, instruction
            ))

        refs = _to_chunk_dicts(docs)
        return {
            "documents": docs,
            "references": refs,
            "context": render_ref_context(refs),
        }

    return ground_node
