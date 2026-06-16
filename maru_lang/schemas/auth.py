from pydantic import BaseModel, Field
from typing import Optional


class SignUpRequest(BaseModel):
    email: str


class LogoutRequest(BaseModel):
    device_id: str


class VerifyCodeRequest(BaseModel):
    device_id: str
    email: str
    code: str


class UserResponse(BaseModel):
    id: int
    email: str
    name: Optional[str] = None

    class Config:
        from_attributes = True


class UpdateMeRequest(BaseModel):
    """본인 표시명(닉네임) 변경 요청."""
    name: str = Field(..., min_length=1, description="전역 표시명(닉네임)")


class ChatTokenResponse(BaseModel):
    chat_token: str
