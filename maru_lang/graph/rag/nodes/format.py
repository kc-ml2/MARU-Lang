"""Format node — convert documents to a readable string + surface metadata.

Produces `result` (the context the generate node uses) and `retrieved_documents`
(dicts for the API / persistence).
"""
from maru_lang.graph.rag.state import RagState


def _to_doc_dicts(docs) -> list[dict]:
    return [
        {
            "document_id": doc.metadata.get("document_id", "unknown"),
            "document_name": doc.metadata.get("document_name", ""),
            "score": doc.metadata.get("score", 0),
            "content": doc.page_content,
            "file_path": doc.metadata.get("file_path", ""),
            "group_id": doc.metadata.get("group_id"),
        }
        for doc in docs
    ]


async def format_node(state: RagState) -> dict:
    """Format retrieved documents into a readable string + retrieved_documents."""
    docs = state["documents"]

    if not docs:
        return {
            "result": f"No documents found for '{state['query']}'.",
            "retrieved_documents": [],
            "rag_log": state.get("rag_log", []) + ["No results to format"],
        }

    formatted = []
    for doc in docs:
        doc_id = doc.metadata.get("document_id", "unknown")
        doc_name = doc.metadata.get("document_name", "")
        score = doc.metadata.get("score", 0)
        formatted.append(
            f"[{doc_id}] {doc_name} (score: {score:.2f})\n"
            f"{doc.page_content}"
        )

    return {
        "result": "\n\n---\n\n".join(formatted),
        "retrieved_documents": _to_doc_dicts(docs),
        "rag_log": state.get("rag_log", []) + [f"Formatted: {len(docs)} documents"],
    }
