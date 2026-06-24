"""Memory extractor node — extract durable user facts/preferences into UserMemory.

Runs in the write-back tail; no-op without user_id. Paired with context_builder
(the read side).
"""
import json
import re

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from maru_lang.constants import FACT_KEYS, MEMORY_EXTRACT_PROMPT, PREFERENCE_KEYS
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
    # Extraction is deterministic classification, not creative generation. Pin it to
    # temperature 0 so it doesn't intermittently return [] (dropping preferences) at the
    # chat model's higher temperature. Falls back to the raw model if a provider rejects
    # the override (e.g. reasoning models that force temperature=1).
    extract_llm = llm.bind(temperature=0)

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

        prompt = MEMORY_EXTRACT_PROMPT.format(message=question)
        try:
            response = await extract_llm.ainvoke(prompt)
            items = _parse_items(response.content or "")
        except Exception:
            try:
                response = await llm.ainvoke(prompt)
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
            key = item.get("key") or None
            # fact/preference 모두 닫힌 키 집합으로만 저장(같은 범주 최신값 upsert).
            # 키가 없거나 범위 밖이면 버린다(임의 사실·모순 선호 누적 방지).
            allowed = FACT_KEYS if kind == UserMemoryKind.FACT else PREFERENCE_KEYS
            if key not in allowed:
                continue
            await upsert_user_memory(user_id, kind, content, key=key)

        return {}

    return memory_extractor_node
