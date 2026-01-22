from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class FileInfo(BaseModel):
    """Individual file information for sync check"""
    fileName: str = Field(..., description="File name")
    createdAt: datetime = Field(..., description="File creation time")
    absolutePath: str = Field(..., description="Absolute path (used for group hierarchy)")
    size: int = Field(..., description="File size (bytes)")
    tempFilePath: Optional[str] = Field(None, description="Temp file path for reading (if different from absolutePath)")

class SyncCheckRequest(BaseModel):
    """Request for checking which files need to be uploaded"""
    folderName: str = Field(..., description="프로젝트 폴더명")
    folderPath: str = Field(..., description="프로젝트 폴더 경로")
    files: List[FileInfo] = Field(..., description="폴더 내 파일 정보 목록")
    description: Optional[str] = Field(None, description="DocumentGroup 설명")


class SyncCheckResponse(BaseModel):
    """Response for sync check"""
    fileIndicesToUpload: List[int] = Field(..., description="Upload required file indices (refers to request.files array)")
    totalFiles: int = Field(..., description="Total number of files")
    processedFiles: Optional[int] = Field(None, description="Number of files to be processed (dry-run result)")
    skippedFiles: Optional[int] = Field(None, description="Number of files to be skipped (dry-run result)")
    unsupportedFileIndices: Optional[List[int]] = Field(None, description="Unsupported file indices (dry-run result)")
    filesToDelete: Optional[List[str]] = Field(None, description="File names to be deleted (exist in DB but not in current files)")


class SyncUploadResponse(BaseModel):
    """Response for batch upload"""
    success: bool = Field(..., description="업로드 성공 여부")
    message: str = Field(..., description="상태 메시지 (예: '배치 1/4 업로드 완료')")
    uploadedCount: int = Field(..., description="업로드된 파일 개수")
    errors: Optional[List[str]] = Field(default=None, description="에러 메시지 목록 (있는 경우)")
