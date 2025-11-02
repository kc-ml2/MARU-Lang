from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class FileInfo(BaseModel):
    """Individual file information for sync check"""
    fileName: str = Field(..., description="파일 이름")
    createdAt: datetime = Field(..., description="파일 생성 시간")
    relativePath: str = Field(..., description="상대 경로 (프로젝트폴더명/경로/파일명)")
    size: int = Field(..., description="파일 크기 (bytes)")


class SyncCheckRequest(BaseModel):
    """Request for checking which files need to be uploaded"""
    folderPath: str = Field(..., description="프로젝트 폴더명")
    files: List[FileInfo] = Field(..., description="폴더 내 파일 정보 목록")


class SyncCheckResponse(BaseModel):
    """Response for sync check"""
    filesToUpload: List[str] = Field(..., description="업로드가 필요한 파일의 relativePath 목록")
    totalFiles: int = Field(..., description="전체 파일 개수")
    message: str = Field(..., description="상태 메시지")


class SyncUploadResponse(BaseModel):
    """Response for batch upload"""
    success: bool = Field(..., description="업로드 성공 여부")
    message: str = Field(..., description="상태 메시지 (예: '배치 1/4 업로드 완료')")
    uploadedCount: int = Field(..., description="업로드된 파일 개수")
    errors: Optional[List[str]] = Field(default=None, description="에러 메시지 목록 (있는 경우)")
