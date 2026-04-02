"""Keyword extraction node — extract search-optimized keywords."""
import re
from langchain_core.language_models import BaseChatModel
from maru_lang.constants import KEYWORD_PROMPT
from maru_lang.graph.rag.state import RagState


def make_keyword_node(llm: BaseChatModel):
    """Create a keyword extraction node bound to the given LLM."""

    async def keyword_node(state: RagState) -> dict:
        query = state["rewritten_query"] or state["query"]
        try:
            response = await llm.ainvoke(KEYWORD_PROMPT.format(query=query))
            raw = response.content.strip()

            tokens = raw.split()
            cleaned = [re.sub(r"[^\w]", "", t) for t in tokens]
            seen: set[str] = set()
            keywords = []
            for t in cleaned:
                if t and t not in seen:
                    seen.add(t)
                    keywords.append(t)
            keywords = keywords[:7]

            return {
                "keywords": keywords,
                "messages": [f"Keywords: {' '.join(keywords)}"],
            }
        except Exception:
            # Fallback: split the query
            return {
                "keywords": query.split()[:5],
                "messages": ["Keyword extraction fallback"],
            }

    return keyword_node
