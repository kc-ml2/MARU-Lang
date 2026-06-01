"""Chat session API schemas."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    title: Optional[str] = Field(default=None, description="세션 제목 (선택)")


class SessionResponse(BaseModel):
    id: str = Field(..., description="세션 ID (= LangGraph thread 그룹 키)")
    title: Optional[str] = None
    status: int = Field(..., description="SessionStatus 값")
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
