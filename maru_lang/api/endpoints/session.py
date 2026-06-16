"""Chat session REST endpoints.

The chat WebSocket only consumes an existing session_id; sessions are created,
listed, and their conversation history is read here.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi_pagination import Page
from fastapi_pagination.ext.tortoise import paginate

from maru_lang.dependencies.auth import get_user
from maru_lang.schemas.session import CreateSessionRequest, SessionResponse
from maru_lang.schemas.chat import ConversationResponse
from maru_lang.services.session import (
    create_session,
    get_or_create_last_session,
    get_session_for_user,
    list_sessions_by_user,
)
from maru_lang.services.chat import fetch_conversations_by_session

router = APIRouter(prefix="/sessions", tags=["Sessions"])


@router.post("", response_model=SessionResponse, status_code=201)
async def create_chat_session(request: CreateSessionRequest, user=Depends(get_user)):
    """새 채팅 세션 생성."""
    return await create_session(user, title=request.title)


@router.get("", response_model=Page[SessionResponse])
async def list_chat_sessions(user=Depends(get_user)):
    """내 세션 목록(최신순, 페이지네이션)."""
    return await paginate(list_sessions_by_user(user))


@router.get("/last", response_model=SessionResponse)
async def get_last_chat_session(user=Depends(get_user)):
    """마지막(가장 최근) 세션 조회. 없으면 새로 생성해 반환."""
    return await get_or_create_last_session(user)


@router.get("/{session_id}/conversations", response_model=Page[ConversationResponse])
async def get_session_conversations(session_id: str, user=Depends(get_user)):
    """세션의 대화 이력(시간순, 페이지네이션). 소유한 세션만."""
    session = await get_session_for_user(session_id, user)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return await paginate(fetch_conversations_by_session(session_id))
