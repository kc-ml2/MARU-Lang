from pydantic import BaseModel
from typing import List, Optional


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


class UserGroupResponse(BaseModel):
    id: int
    name: str
    manager: Optional[UserResponse] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class UserGroupsResponse(BaseModel):
    groups: List[UserGroupResponse]
    total: int


class ChatTokenResponse(BaseModel):
    chat_token: str
