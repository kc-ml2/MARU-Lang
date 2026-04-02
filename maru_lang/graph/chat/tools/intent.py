"""Intent extraction — rewrite query based on conversation context."""
from langchain_core.language_models import BaseChatModel
from maru_lang.constants import INTENT_PROMPT


async def extract_intent(query: str, llm: BaseChatModel) -> str:
    """Rewrite a query to better capture user intent.

    Args:
        query: Original user query.
        llm: LLM to use for rewriting.

    Returns:
        Rewritten query optimized for search.
    """
    response = await llm.ainvoke(
        f"{INTENT_PROMPT}\n\nOriginal query: {query}\n\nRewritten query:"
    )
    rewritten = response.content.strip()
    return rewritten if rewritten else query
