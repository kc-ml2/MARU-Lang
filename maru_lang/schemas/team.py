from pydantic import BaseModel, ConfigDict, EmailStr


class CreateTeamRequest(BaseModel):
    name: str
    description: str | None = None


class InviteMemberRequest(BaseModel):
    email: EmailStr


class TeamMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    name: str | None = None
    role: str


class TeamSummaryResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    role: str


class TeamDetailResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    members: list[TeamMemberResponse]
    storage_count: int
