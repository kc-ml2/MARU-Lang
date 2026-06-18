"""User persistent memory service — session-independent user facts/preferences."""
from typing import List, Optional

from maru_lang.core.relation_db.models.chat import UserMemory
from maru_lang.enums.chat import UserMemoryKind


async def list_user_memories(user_id: int) -> List[UserMemory]:
    """Return all of the user's memories (facts/preferences), newest first."""
    return await UserMemory.filter(user_id=user_id).all()


async def format_user_memory(user_id: int) -> tuple[str, str]:
    """단일 조회로 (facts_block, style_directive)를 만든다.

    - facts_block: 고정 사실 → 참고용 [사용자 정보] 블록 (memory_context로).
    - style_directive: 응답 선호 → 별도 지침 블록. 수동적 '이전 대화 맥락'에 묻으면
      새 세션에서 무시되므로 generate가 독립 SystemMessage로 주입한다.
    둘 다 없으면 해당 문자열은 ''.
    """
    memories = await list_user_memories(user_id)
    facts, prefs = [], []
    for m in memories:
        line = f"{m.key}: {m.content}" if m.key else m.content
        (facts if m.kind == UserMemoryKind.FACT else prefs).append(line)
    facts_block = ("[사용자 정보]\n사실:\n- " + "\n- ".join(facts)) if facts else ""
    style_directive = ("[사용자 선호 — 답변에 반영]\n- " + "\n- ".join(prefs)) if prefs else ""
    return facts_block, style_directive


async def upsert_user_memory(
    user_id: int,
    kind: UserMemoryKind,
    content: str,
    key: Optional[str] = None,
) -> UserMemory:
    """Upsert a memory.

    - with key: update-or-create by (user, kind, key) — keeps the latest value
      for that category. FACT uses free-form keys (e.g. name); PREFERENCE uses a
      closed category set (tone/language/format/length/persona).
    - without key: skip if an identical content already exists, else create.
    """
    content = (content or "").strip()

    if key:
        existing = await UserMemory.get_or_none(user_id=user_id, kind=kind, key=key)
        if existing:
            existing.content = content
            await existing.save()
            return existing
        return await UserMemory.create(user_id=user_id, kind=kind, key=key, content=content)

    dup = await UserMemory.get_or_none(user_id=user_id, kind=kind, content=content)
    if dup:
        return dup
    return await UserMemory.create(user_id=user_id, kind=kind, content=content)


async def delete_user_memory(user_id: int, memory_id: int) -> bool:
    """Delete one memory owned by the user. Returns True if a row was removed."""
    deleted = await UserMemory.filter(id=memory_id, user_id=user_id).delete()
    return bool(deleted)


async def clear_user_memories(user_id: int) -> int:
    """Delete all of the user's memories. Returns the number removed."""
    return await UserMemory.filter(user_id=user_id).delete()
