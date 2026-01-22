from pydantic import BaseModel
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


class ChatTokenResponse(BaseModel):
    chat_token: str
