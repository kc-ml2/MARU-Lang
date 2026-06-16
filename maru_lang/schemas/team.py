from pydantic import BaseModel
from typing import Optional


class CreateTeamRequest(BaseModel):
    name: str
    description: Optional[str] = None


class InviteMemberRequest(BaseModel):
    email: str
    name: str


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
