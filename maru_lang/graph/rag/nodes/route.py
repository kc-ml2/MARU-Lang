"""Route node — classify whether the question needs document search.

A simple classifier node (SEARCH / DIRECT) replaces ReAct tool-calling.
"""
from langchain_core.language_models import BaseChatModel

from maru_lang.constants import ROUTE_PROMPT
from maru_lang.graph.rag.state import RagState


def make_route_node(llm: BaseChatModel):
    """Classify the question as needing search (SEARCH) or not (DIRECT)."""

    async def route_node(state: RagState) -> dict:
        messages = state.get("messages", [])
        question = messages[-1].content if messages else ""
        # Include prior context so follow-up questions are classified correctly.
        memory = state.get("memory_context")
        if memory:
            question = f"[이전 맥락]\n{memory}\n\n[현재 질문]\n{question}"
        try:
            response = await llm.ainvoke(ROUTE_PROMPT.format(question=question))
            verdict = (response.content or "").strip().upper()
        except Exception:
            verdict = "SEARCH"  # on failure, default to searching (safer)
        decision = "direct" if verdict.startswith("DIRECT") else "search"
        return {
            "route": decision,
            "rag_log": state.get("rag_log", []) + [f"Route: {decision}"],
        }

    return route_node


def route_decision(state: RagState) -> str:
    """Map the route verdict to the next node."""
    return "generate" if state.get("route") == "direct" else "search_entry"
