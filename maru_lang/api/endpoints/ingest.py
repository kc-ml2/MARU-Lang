"""Ingest API endpoints - LangGraph 기반"""
import json
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form

from maru_lang.enums.auth import UserRoleCode
from maru_lang.dependencies.auth import get_user_with_role, User
from maru_lang.schemas.ingest import FileInfo, SyncCheckRequest, SyncCheckResponse
from maru_lang.utils.file_upload import save_uploaded_file
from maru_lang.pipelines.ingest import run_ingest, stream_ingest

router = APIRouter(
    prefix="/folder",
    tags=["Ingest"],
)


@router.post("/sync/upload")
async def upload_and_ingest(
    file: UploadFile = File(..., description="File to upload"),
    folderName: str = Form(..., description="Project folder name"),
    folderPath: str = Form(..., description="Project folder path"),
    fileMetadata: str = Form(
        ..., description="File metadata JSON: {fileName, createdAt, relativePath, size}"
    ),
    userGroupIds: str = Form(None, description="User group IDs JSON array"),
    description: str = Form(None, description="DocumentGroup description"),
    user: User = Depends(get_user_with_role(UserRoleCode.EDITOR)),
):
    upload_dir = None
    try:
        # Parse fileMetadata
        try:
            file_meta = json.loads(fileMetadata)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid fileMetadata format")

        # Create upload directory
        upload_base_dir = Path(tempfile.gettempdir()) / "maru_lang_uploads"
        group_name = f"{user.name}/{folderName}"
        upload_dir = upload_base_dir / group_name

        # Save uploaded file
        file_info = await save_uploaded_file(file, file_meta, upload_dir)

        # Run ingest (LangGraph)
        result = await run_ingest(
            files=[file_info],
            team_id=user.id,  # TODO: team_id from request
            re_embed=False,
        )

        return {
            "success": True,
            "message": "Upload and ingestion completed",
            "data": {
                "fileName": file_info.fileName,
                "totalFiles": result.total_files,
                "processedFiles": result.processed_files,
                "skippedFiles": result.skipped_files,
                "failedFiles": result.failed_files,
                "failedDetails": result.failed_details,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if upload_dir and upload_dir.exists():
            try:
                shutil.rmtree(upload_dir)
            except Exception:
                pass
