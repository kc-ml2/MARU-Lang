"""User persistent memory REST endpoints — list and delete the caller's memories."""
from fastapi import APIRouter, Depends, HTTPException

from maru_lang.dependencies.auth import get_user
from maru_lang.schemas.memory import MemoryResponse
from maru_lang.services.memory import (
    list_user_memories,
    delete_user_memory,
    clear_user_memories,
)

router = APIRouter(prefix="/memories", tags=["Memory"])


@router.get("", response_model=list[MemoryResponse])
async def get_my_memories(user=Depends(get_user)):
    """내 영구 메모리(사실/선호) 목록."""
    return await list_user_memories(user.id)


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(memory_id: int, user=Depends(get_user)):
    """메모리 한 건 삭제 (소유자만)."""
    if not await delete_user_memory(user.id, memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")


@router.delete("", status_code=204)
async def clear_memories(user=Depends(get_user)):
    """내 메모리 전체 삭제."""
    await clear_user_memories(user.id)
