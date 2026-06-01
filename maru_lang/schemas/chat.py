from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class DocumentReference(BaseModel):
    """Cleaned document reference without page_content (for API responses)"""
    id: str = Field(..., description="Document chunk ID")
    source: str = Field(..., description="Document name/source")
    document_id: Optional[str] = Field(
        None, description="Original document ID")
    content: Optional[str] = Field(
        None, description="Document content preview")
    group: Optional[str] = Field(None, description="Document group")
    file_path: Optional[str] = Field(None, description="File path")


class ChatRequest(BaseModel):
    content: str
    session_start_time: Optional[datetime] = Field(
        default=None,
        description="세션 시작 시간")


class ChatResponse(BaseModel):
    answer: str
    references: list[DocumentReference]


class ConversationResponse(BaseModel):
    id: int
    question: str
    answer: str
    created_at: datetime

    class Config:
        from_attributes = True


# ============ WebSocket Messages (Client -> Server) ============

class WSAuthMessage(BaseModel):
    type: str = "auth"
    chat_token: str


class WSChatMessage(BaseModel):
    type: str = "message"
    content: str


# ============ WebSocket Messages (Server -> Client) ============

class WSAuthenticatedMessage(BaseModel):
    type: str = "authenticated"


class WSAuthErrorMessage(BaseModel):
    type: str = "auth_error"
    message: Optional[str] = None


class WSStartMessage(BaseModel):
    type: str = "start"


class WSStreamMessage(BaseModel):
    type: str = "stream"
    content: str


class WSCompleteMessage(BaseModel):
    type: str = "complete"


class WSErrorMessage(BaseModel):
    type: str = "error"
    message: Optional[str] = None
