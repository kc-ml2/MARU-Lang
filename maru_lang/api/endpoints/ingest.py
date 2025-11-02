import os
import tempfile
from pathlib import Path
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from maru_lang.enums.auth import UserRoleCode
from maru_lang.dependencies.auth import get_user_with_role, User
from maru_lang.schemas.ingest import (
    SyncCheckRequest,
    SyncCheckResponse,
    SyncUploadResponse,
)
from maru_lang.services.ingest import check_files_to_upload, get_or_create_document_group
from maru_lang.configs.system_config import get_system_config

config = get_system_config()

router = APIRouter(
    prefix="/folder",
    tags=["Ingest"]
)


@router.post("/sync/check", response_model=SyncCheckResponse)
async def check_sync_status(
    request: SyncCheckRequest,
    user: User = Depends(get_user_with_role(UserRoleCode.EDITOR))
):
    """
    Check which files need to be uploaded by comparing with existing files in the database.

    Compares fileName, createdAt, and relativePath to determine new or modified files.

    Args:
        request: Folder path and file information list
        user: Authenticated user

    Returns:
        List of files that need to be uploaded
    """
    try:
        # Convert FileInfo objects to dict format for service function
        files_data = [
            {
                "fileName": file_info.fileName,
                "createdAt": file_info.createdAt,
                "relativePath": file_info.relativePath
            }
            for file_info in request.files
        ]

        # Check which files need to be uploaded
        files_to_upload = await check_files_to_upload(
            folder_path=request.folderPath,
            files=files_data
        )

        return SyncCheckResponse(
            filesToUpload=files_to_upload,
            totalFiles=len(request.files),
            message=f"{len(files_to_upload)}개의 새로운 파일이 있습니다." if files_to_upload else "모든 파일이 최신 상태입니다."
        )

    except Exception as e:
        print(f"❌ Sync check error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/upload", response_model=SyncUploadResponse)
async def upload_batch(
    folderPath: str = Form(..., description="프로젝트 폴더명"),
    batchIndex: int = Form(..., description="현재 배치 번호 (0부터 시작)"),
    totalBatches: int = Form(..., description="전체 배치 개수"),
    files: List[UploadFile] = File(..., description="업로드할 파일 배열 (최대 10개)"),
    user: User = Depends(get_user_with_role(UserRoleCode.EDITOR))
):
    """
    Upload files in batches (max 10 files per batch).

    Saves files to a temporary upload directory and creates Document records.
    The IngestPipeline will process these files asynchronously.

    Batch processing example for 35 files:
    - Batch 0: 10 files
    - Batch 1: 10 files
    - Batch 2: 10 files
    - Batch 3: 5 files (last batch)

    Args:
        folderPath: Project folder name
        batchIndex: Current batch number (0-indexed)
        totalBatches: Total number of batches
        files: File array to upload (max 10 files)
        user: Authenticated user

    Returns:
        Upload status with count and message
    """
    try:
        # Validate batch size
        if len(files) > 10:
            raise HTTPException(
                status_code=400,
                detail="배치당 최대 10개의 파일만 업로드 가능합니다."
            )

        # Validate batch index
        if batchIndex < 0 or batchIndex >= totalBatches:
            raise HTTPException(
                status_code=400,
                detail=f"배치 인덱스가 올바르지 않습니다. (0-{totalBatches-1} 범위)"
            )

        # Create upload directory
        # Use a persistent directory for uploaded files
        upload_base_dir = Path(tempfile.gettempdir()) / "maru_lang_uploads"
        upload_dir = upload_base_dir / folderPath
        upload_dir.mkdir(parents=True, exist_ok=True)

        uploaded_files = []

        # Save uploaded files
        for uploaded_file in files:
            try:
                # Get original filename
                filename = uploaded_file.filename
                if not filename:
                    continue

                # Create full file path
                file_path = upload_dir / filename

                # Ensure parent directory exists
                file_path.parent.mkdir(parents=True, exist_ok=True)

                # Save file
                content = await uploaded_file.read()
                with open(file_path, "wb") as f:
                    f.write(content)

                uploaded_files.append(filename)

                print(f"   ✓ Saved: {filename} ({len(content)} bytes)")

            except Exception as e:
                print(f"   ✗ Failed to save {uploaded_file.filename}: {str(e)}")
                # Continue with other files even if one fails

        # Log upload completion
        print(f"📁 Batch upload: {folderPath}")
        print(f"   Batch {batchIndex + 1}/{totalBatches}")
        print(f"   Files saved: {len(uploaded_files)}/{len(files)}")
        print(f"   Upload directory: {upload_dir}")
        print(f"   User: {user.email}")

        # TODO: Trigger IngestPipeline for final batch
        # if batchIndex == totalBatches - 1:
        #     # All batches uploaded, trigger ingestion
        #     await trigger_ingestion(upload_dir, folderPath, user.id)

        return SyncUploadResponse(
            success=True,
            message=f"배치 {batchIndex + 1}/{totalBatches} 업로드 완료",
            uploadedCount=len(uploaded_files),
            errors=[f"Failed: {f.filename}" for f in files if f.filename not in uploaded_files] if len(uploaded_files) < len(files) else None
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Upload error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"배치 {batchIndex + 1}/{totalBatches} 업로드에 실패했습니다: {str(e)}"
        )
