"""Intent extraction node — rewrite query for better search."""
from langchain_core.language_models import BaseChatModel
from maru_lang.constants import INTENT_PROMPT
from maru_lang.graph.rag.state import RagState


def make_intent_node(llm: BaseChatModel):
    """Create an intent extraction node bound to the given LLM."""

    async def intent_node(state: RagState) -> dict:
        query = state["query"]
        # Include recent conversation context so follow-up questions (pronouns,
        # ellipsis, one-word replies) are rewritten into self-contained queries.
        memory = state.get("memory_context")
        if memory:
            prompt = (
                f"{INTENT_PROMPT}\n\n"
                f"[이전 대화 맥락]\n{memory}\n\n"
                f"[현재 메시지]\n{query}\n\nRewritten query:"
            )
        else:
            prompt = f"{INTENT_PROMPT}\n\nOriginal query: {query}\n\nRewritten query:"
        try:
            response = await llm.ainvoke(prompt)
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
