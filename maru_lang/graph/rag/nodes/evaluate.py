"""Evaluate node — decide if retrieval results are sufficient."""
import logging
from typing import Optional

from langchain_core.language_models import BaseChatModel

from maru_lang.constants import (
    RAG_EVALUATE_MAX_RETRIES,
    RAG_EVALUATE_MIN_DOCS,
    RAG_EVALUATE_MIN_AVG_SCORE,
    RAG_EVALUATE_PROMPT,
)
from maru_lang.graph.rag.state import RagState

logger = logging.getLogger(__name__)


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
            msg = f"Evaluate: max retries ({RAG_EVALUATE_MAX_RETRIES}) reached"
            logger.debug(msg)
            return {
                "evaluation": "max_retry",
                "messages": [msg],
            }

        if not docs:
            msg = f"Evaluate: FAIL (retry {retry + 1}/{RAG_EVALUATE_MAX_RETRIES}) — 0 documents returned"
            logger.debug(msg)
            return {
                "evaluation": "fail",
                "retry_count": retry + 1,
                "excluded_doc_ids": [],
                "messages": [msg],
            }

        if method == "llm" and llm is not None:
            reason = await _llm_evaluate(state, llm)
        else:
            reason = _rule_evaluate(docs)

        if reason is not None:
            current_doc_ids = [doc.id for doc in docs if doc.id]
            msg = f"Evaluate[{method}]: FAIL (retry {retry + 1}/{RAG_EVALUATE_MAX_RETRIES}) — {reason}, excluding {len(current_doc_ids)} doc_ids"
            logger.debug(msg)
            return {
                "evaluation": "fail",
                "retry_count": retry + 1,
                "excluded_doc_ids": current_doc_ids,
                "messages": [msg],
            }

        # pass
        doc_count = len(docs)
        avg_score = sum(d.metadata.get("score", 0) for d in docs) / doc_count
        msg = f"Evaluate[{method}]: PASS ({doc_count} docs, avg_score={avg_score:.3f})"
        logger.debug(msg)
        logger.debug("Doc scores: %s", [round(d.metadata.get("score", 0), 3) for d in docs])
        return {
            "evaluation": "pass",
            "messages": [msg],
        }

    return evaluate_node


def evaluate_route(state: RagState) -> str:
    """Routing function — reads evaluation marker set by evaluate_node."""
    evaluation = state.get("evaluation", "pass")

    if evaluation == "fail" and state["retry_count"] < RAG_EVALUATE_MAX_RETRIES:
        return "retry"

    # "pass", "max_retry", or retry_count already at limit → proceed
    return "rerank"


def _rule_evaluate(docs) -> Optional[str]:
    """Rule-based evaluation: check doc count and average score.

    Returns None if sufficient, or a reason string if not.
    """
    if len(docs) < RAG_EVALUATE_MIN_DOCS:
        return f"doc_count={len(docs)}<{RAG_EVALUATE_MIN_DOCS}"
    avg_score = sum(d.metadata.get("score", 0) for d in docs) / len(docs)
    if avg_score < RAG_EVALUATE_MIN_AVG_SCORE:
        return f"avg_score={avg_score:.3f}<{RAG_EVALUATE_MIN_AVG_SCORE}"
    return None


async def _llm_evaluate(state: RagState, llm: BaseChatModel) -> Optional[str]:
    """LLM-based evaluation: ask LLM if documents are sufficient.

    Returns None if sufficient, or a reason string if not.
    """
    query = state["rewritten_query"] or state["query"]
    docs = state["documents"]

    doc_texts = "\n\n".join(
        f"[{i+1}] {d.page_content[:300]}" for i, d in enumerate(docs[:5])
    )

    response = await llm.ainvoke(
        RAG_EVALUATE_PROMPT.format(query=query, documents=doc_texts)
    )
    verdict = response.content.strip().lower()

    # Strict: only the exact token 'sufficient' (with optional trailing punctuation)
    # passes. Anything else — 'insufficient', 'not sufficient', verbose prose
    # containing the word, empty response — falls through to retry (safe-fail).
    normalized = verdict.rstrip(".!?,;: \t\n")
    if normalized == "sufficient":
        return None
    return f'verdict="{verdict[:80]}", query="{query[:80]}"'
