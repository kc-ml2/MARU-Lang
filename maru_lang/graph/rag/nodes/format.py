"""Format node — convert documents to formatted result string."""
from maru_lang.graph.rag.state import RagState


async def format_node(state: RagState) -> dict:
    """Format retrieved documents into a readable string."""
    docs = state["documents"]

    if not docs:
        return {
            "result": f"No documents found for '{state['query']}'.",
            "messages": ["No results to format"],
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
        "messages": [f"Formatted: {len(docs)} documents"],
    }
