"""DocumentSource API schemas."""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel


# --- Source ---

class DocumentSourceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    source_path: str
    file_pattern: Optional[str] = None


class DocumentSourceResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    source_path: str
    file_pattern: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime
    connected_teams: list["TeamSummaryRef"] = []

    class Config:
        from_attributes = True


class TeamSummaryRef(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    source_path: Optional[str] = None
    file_pattern: Optional[str] = None


# --- Connect / Disconnect ---

class ConnectSourceRequest(BaseModel):
    team_ids: list[int]


class ConnectResponse(BaseModel):
    source_id: int
    connected_team_ids: list[int]
    root_group_id: int
    root_group_name: str


# --- Sync ---

class SyncResponse(BaseModel):
    source_id: int
    source_path: str
    status: str  # "syncing" | "completed" | "error"
    files_processed: int = 0
    files_new: int = 0
    files_updated: int = 0
    files_deleted: int = 0
    error: Optional[str] = None


class SourceDetailResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    source_path: str
    file_pattern: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime
    root_group_id: Optional[int] = None
    root_group_name: Optional[str] = None
    connected_team_ids: list[int] = []
