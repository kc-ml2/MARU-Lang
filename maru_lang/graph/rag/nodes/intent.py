"""Intent extraction node — rewrite query for better search."""
from langchain_core.language_models import BaseChatModel
from maru_lang.constants import INTENT_PROMPT
from maru_lang.graph.rag.state import RagState


def make_intent_node(llm: BaseChatModel):
    """Create an intent extraction node bound to the given LLM."""

    async def intent_node(state: RagState) -> dict:
        query = state["query"]
        try:
            response = await llm.ainvoke(
                f"{INTENT_PROMPT}\n\nOriginal query: {query}\n\nRewritten query:"
            )
            rewritten = response.content.strip()
            return {
                "rewritten_query": rewritten if rewritten else query,
                "rag_log": state.get("rag_log", []) + [f"Intent: {query} → {rewritten}"],
            }
        except Exception:
            return {
                "rewritten_query": query,
                "rag_log": state.get("rag_log", []) + ["Intent extraction skipped"],
            }

    return intent_node
