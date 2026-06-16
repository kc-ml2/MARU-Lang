"""LLM selection API schemas."""
from typing import Optional

from pydantic import BaseModel, Field


class LlmResponse(BaseModel):
    """선택 가능한(enabled) LLM 항목."""
    id: int
    name: str
    provider: str
    model_name: str

    class Config:
        from_attributes = True


class UserLlmResponse(BaseModel):
    """현재 사용자에게 배정된 LLM (미배정이면 null)."""
    assigned_llm: Optional[LlmResponse] = None


class UpdateUserLlmRequest(BaseModel):
    llm_id: int = Field(..., description="배정할 LLM id (GET /llms 목록의 항목)")
