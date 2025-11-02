from pydantic import BaseModel
from typing import List


class SignUpRequest(BaseModel):
    email: str


class LogoutRequest(BaseModel):
    device_id: str


class VerifyCodeRequest(BaseModel):
    device_id: str
    email: str
    code: str


class UserGroupResponse(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class UserGroupsResponse(BaseModel):
    groups: List[UserGroupResponse]
    total: int
