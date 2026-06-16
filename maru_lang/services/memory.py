"""User persistent memory service — session-independent user facts/preferences."""
from typing import List, Optional

from maru_lang.core.relation_db.models.chat import UserMemory
from maru_lang.enums.chat import UserMemoryKind


async def list_user_memories(user_id: int) -> List[UserMemory]:
    """Return all of the user's memories (facts/preferences), newest first."""
    return await UserMemory.filter(user_id=user_id).all()


async def upsert_user_memory(
    user_id: int,
    kind: UserMemoryKind,
    content: str,
    key: Optional[str] = None,
) -> UserMemory:
    """Upsert a memory.

    - FACT + key: update-or-create by (user, kind, key) — e.g. name keeps latest.
    - otherwise: skip if an identical content already exists, else create.
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
