"""Memory extractor node — extract durable user facts/preferences into UserMemory.

Runs in the write-back tail; no-op without user_id. Paired with context_builder
(the read side).
"""
import json
import re

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from maru_lang.constants import MEMORY_EXTRACT_PROMPT
from maru_lang.enums.chat import UserMemoryKind
from maru_lang.services.memory import upsert_user_memory
from maru_lang.graph.rag.state import RagState

_KIND = {"fact": UserMemoryKind.FACT, "preference": UserMemoryKind.PREFERENCE}


def _parse_items(text: str) -> list[dict]:
    """Robustly parse a JSON array from LLM output (tolerates code fences/extra text)."""
    if not text:
        return []
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def make_memory_extractor_node(llm: BaseChatModel):
    """Extract facts/preferences from the user message and upsert into UserMemory."""

    async def memory_extractor_node(state: RagState) -> dict:
        user_id = state.get("user_id")
        if not user_id:
            return {}

        question = state.get("question")
        if not question:
            humans = [m for m in state.get("messages", []) if isinstance(m, HumanMessage)]
            question = humans[0].content if humans else ""
        if not question:
            return {}

        try:
            response = await llm.ainvoke(MEMORY_EXTRACT_PROMPT.format(message=question))
            items = _parse_items(response.content or "")
        except Exception:
            items = []

        for item in items:
            if not isinstance(item, dict):
                continue
            kind = _KIND.get(str(item.get("kind", "")).lower())
            content = (item.get("content") or "").strip()
            if not kind or not content:
                continue
            await upsert_user_memory(user_id, kind, content, key=item.get("key") or None)

        return {}

    return memory_extractor_node
