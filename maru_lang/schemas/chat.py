from typing import Any
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from maru_lang.core.vector_db.retrieve_document import RetrieveDocument


class ChatRequest(BaseModel):
    content: str
    session_start_time: Optional[datetime] = Field(
        default=None,
        description="세션 시작 시간")

class ChatResponse(BaseModel):
    answer: str
    references: list[RetrieveDocument]


class ConversationResponse(BaseModel):
    id: int
    question: str
    answer: str
    created_at: datetime
