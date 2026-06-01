"""Chat session REST endpoints.

The chat WebSocket only consumes an existing session_id; sessions are created
and retrieved here.
"""
from fastapi import APIRouter, Depends

from maru_lang.dependencies.auth import get_user
from maru_lang.schemas.session import CreateSessionRequest, SessionResponse
from maru_lang.services.session import create_session, get_or_create_last_session

router = APIRouter(prefix="/sessions", tags=["Sessions"])


@router.post("", response_model=SessionResponse, status_code=201)
async def create_chat_session(request: CreateSessionRequest, user=Depends(get_user)):
    """새 채팅 세션 생성."""
    return await create_session(user, title=request.title)


@router.get("/last", response_model=SessionResponse)
async def get_last_chat_session(user=Depends(get_user)):
    """마지막(가장 최근) 세션 조회. 없으면 새로 생성해 반환."""
    return await get_or_create_last_session(user)
