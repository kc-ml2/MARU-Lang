"""Shared chunk→ref conversion and id-tagged context rendering.

Both grounding (fuzzy RAG hits) and reference binding (standard/baseline anchors)
turn vector-DB chunks into ref dicts and render them into an id-tagged context
block for the draft prompt; the common core lives here so the two stay in sync.
"""
from maru_lang.graph.doc.constants import UNKNOWN_DOC_ID


def base_ref(chunk, *, score_default) -> dict:
    """The fields every ref dict shares, from a vector-DB chunk (LangChain Document).

    Callers add their own extras (RAG: file_path/group_id; anchor: kind).
    """
    return {
        "chunk_id": chunk.id,
        "document_id": chunk.metadata.get("document_id", UNKNOWN_DOC_ID),
        "document_name": chunk.metadata.get("document_name", ""),
        "score": chunk.metadata.get("score", score_default),
        "content": chunk.page_content,
    }


def render_ref_context(refs: list[dict]) -> str:
    """Tag each chunk with its id so the draft prompt can cite source_refs."""
    return "\n\n---\n\n".join(
        f"[{r['chunk_id']}] {r.get('document_name', '')}\n{r['content']}" for r in refs
    )
