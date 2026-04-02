"""Evaluate node — decide if retrieval results are sufficient."""
from typing import Optional

from langchain_core.language_models import BaseChatModel

from maru_lang.constants import (
    RAG_EVALUATE_MAX_RETRIES,
    RAG_EVALUATE_MIN_DOCS,
    RAG_EVALUATE_MIN_AVG_SCORE,
    RAG_EVALUATE_PROMPT,
)
from maru_lang.graph.rag.state import RagState


def make_evaluate_node(method: str = "rule", llm: Optional[BaseChatModel] = None):
    """Create an evaluate node.

    Args:
        method: "rule" (score/count based) or "llm" (LLM judges sufficiency).
        llm: Required if method is "llm".
    """

    async def evaluate_node(state: RagState) -> dict:
        docs = state["documents"]
        retry = state["retry_count"]

        if retry >= RAG_EVALUATE_MAX_RETRIES:
            return {"messages": [f"Evaluate: max retries ({RAG_EVALUATE_MAX_RETRIES}) reached"]}

        if not docs:
            return {"retry_count": retry + 1, "messages": ["Evaluate: no results → retry"]}

        if method == "llm" and llm is not None:
            sufficient = await _llm_evaluate(state, llm)
        else:
            sufficient = _rule_evaluate(docs)

        if not sufficient:
            return {"retry_count": retry + 1, "messages": ["Evaluate: insufficient → retry"]}

        return {"messages": ["Evaluate: sufficient"]}

    return evaluate_node


def evaluate_route(state: RagState) -> str:
    """Routing function for conditional edge after evaluate node."""
    docs = state["documents"]
    retry = state["retry_count"]

    if retry >= RAG_EVALUATE_MAX_RETRIES:
        return "rerank"

    if not docs:
        return "retry"

    # If retry_count was just incremented by evaluate_node, it means insufficient
    # Check by comparing: if retry > 0 and the node incremented it, route to retry
    # Simpler: use documents quality as signal
    avg_score = sum(d.metadata.get("score", 0) for d in docs) / len(docs)
    if len(docs) < RAG_EVALUATE_MIN_DOCS or avg_score < RAG_EVALUATE_MIN_AVG_SCORE:
        return "retry"

    return "rerank"


def _rule_evaluate(docs) -> bool:
    """Rule-based evaluation: check doc count and average score."""
    if len(docs) < RAG_EVALUATE_MIN_DOCS:
        return False
    avg_score = sum(d.metadata.get("score", 0) for d in docs) / len(docs)
    return avg_score >= RAG_EVALUATE_MIN_AVG_SCORE


async def _llm_evaluate(state: RagState, llm: BaseChatModel) -> bool:
    """LLM-based evaluation: ask LLM if documents are sufficient."""
    query = state["rewritten_query"] or state["query"]
    docs = state["documents"]

    doc_texts = "\n\n".join(
        f"[{i+1}] {d.page_content[:300]}" for i, d in enumerate(docs[:5])
    )

    response = await llm.ainvoke(
        RAG_EVALUATE_PROMPT.format(query=query, documents=doc_texts)
    )
    verdict = response.content.strip().lower()
    return "sufficient" in verdict
