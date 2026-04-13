"""Ingest API schemas."""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class FileInfo(BaseModel):
    """File information for ingest pipeline."""
    fileName: str
    createdAt: datetime
    absolutePath: str
    size: int
    tempFilePath: Optional[str] = None  # storage path after upload


# --- Upload ---

class UploadResponse(BaseModel):
    document_id: str
    name: str
    status: str  # "uploading"
    is_reupload: bool = False


# --- Status ---

class AuditLogEntry(BaseModel):
    action: str
    user_name: Optional[str] = None
    detail: dict = {}
    created_at: datetime


class DocumentStatusItem(BaseModel):
    id: str
    name: str
    status: str
    folder_path: Optional[str] = None
    file_size: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    error: Optional[str] = None
    audit_logs: list[AuditLogEntry] = []


class StatusResponse(BaseModel):
    team_id: int
    documents: list[DocumentStatusItem]
    total: int


# --- Check ---

class CheckFileInfo(BaseModel):
    fileName: str
    absolutePath: str
    size: int
    mtime: float  # unix timestamp


class CheckRequest(BaseModel):
    team_id: int
    files: list[CheckFileInfo]


class CheckResponse(BaseModel):
    indices_to_upload: list[int]
    total: int


# --- Delete ---

class DeleteResponse(BaseModel):
    document_id: str
    deleted: bool
