from pydantic import BaseModel
from typing import Optional


class CreateTeamRequest(BaseModel):
    name: str
    description: Optional[str] = None


class InviteMemberRequest(BaseModel):
    # 초대는 이메일만 받는다. 표시명은 각 사용자가 본인 닉네임(User.name)으로
    # 직접 설정하며, 초대 시 다른 사용자의 이름을 덮어쓰지 않는다.
    email: str


class TeamMemberResponse(BaseModel):
    id: int
    email: str
    name: Optional[str] = None
    role: str

    class Config:
        from_attributes = True


class FolderResponse(BaseModel):
    id: int
    name: str
    document_count: int


class TeamSummaryResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    role: str


class TeamDetailResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    members: list[TeamMemberResponse]
    folders: list[FolderResponse]
