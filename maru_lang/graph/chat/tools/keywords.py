"""Keyword extraction — extract search-optimized keywords from a query."""
import re
from langchain_core.language_models import BaseChatModel
from maru_lang.constants import KEYWORD_PROMPT


async def extract_keywords(query: str, llm: BaseChatModel) -> list[str]:
    """Extract search-optimized keywords from a query.

    Args:
        query: Search query.
        llm: LLM to use for extraction.

    Returns:
        List of keywords.
    """
    response = await llm.ainvoke(KEYWORD_PROMPT.format(query=query))
    raw = response.content.strip()

    tokens = raw.split()
    cleaned = [re.sub(r"[^\w]", "", t) for t in tokens]

    seen: set[str] = set()
    unique: list[str] = []
    for t in cleaned:
        if t and t not in seen:
            seen.add(t)
            unique.append(t)

    return unique[:7]
