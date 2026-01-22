import os
import json
import shutil
import tempfile
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from maru_lang.enums.auth import UserRoleCode
from maru_lang.dependencies.auth import get_user_with_role, User
from maru_lang.pipelines.base import PipelineMessage
from maru_lang.schemas.ingest import FileInfo, SyncCheckRequest, SyncCheckResponse
from maru_lang.configs.system_config import get_system_config
from maru_lang.utils.file_upload import save_uploaded_file

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

    Runs a dry-run simulation to determine:
    - Which files need processing (new or modified)
    - Which files will be skipped (unchanged)
    - Which files are unsupported

    Args:
        request: Folder path and file information list
        user: Authenticated user

    Returns:
        File indices that need to be uploaded (refers to request.files array)
    """
    try:
        # Create group name with user identifier: {username}/{folderName}
        group_name = f"{user.name}/{request.folderName}"

        pipeline = create_ingest_pipeline(
            upload_path=Path(request.folderPath),
            group_name=group_name,
            manager_id=user.id,
            dry_run=True,
            files=request.files,
            description=request.description
        )

        result = None
        async for item in pipeline.run():
            if isinstance(item, PipelineMessage):
                print(f"[DRY-RUN] {item.message}")
            # elif isinstance(item, PipelineComplete):
            #     result = item.data
            #     print(f"[DRY-RUN] Complete: {result}")

        if result is None:
            raise HTTPException(
                status_code=500, detail="Dry-run pipeline did not return result")

        return SyncCheckResponse(
            fileIndicesToUpload=result.files_to_process_indices or [],
            totalFiles=result.total_files,
            processedFiles=result.processed_files,
            skippedFiles=result.skipped_files,
            unsupportedFileIndices=result.unsupported_file_indices or [],
            filesToDelete=result.files_to_delete or [],
        )

    except Exception as e:
        print(f"❌ Sync check error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/upload")
async def upload_and_ingest(
    file: UploadFile = File(..., description="File to upload"),
    folderName: str = Form(..., description="Project folder name"),
    folderPath: str = Form(..., description="Project folder path"),
    fileMetadata: str = Form(
        ..., description="File metadata JSON: {fileName, createdAt, relativePath, size}"),
    userGroupIds: str = Form(None, description="User group IDs JSON array"),
    description: str = Form(None, description="DocumentGroup description"),
    maruSync: bool = Form(False, description="with maruSync"),
    user: User = Depends(get_user_with_role(UserRoleCode.EDITOR)),
):
    upload_dir = None
    try:
        group_name = f"{user.name}/{folderName}"

        # Parse userGroupIds from JSON string
        user_group_id_list = []
        if userGroupIds:
            try:
                user_group_id_list = json.loads(userGroupIds)
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=400, detail="Invalid userGroupIds format")

        # Parse fileMetadata from JSON string
        try:
            file_meta = json.loads(fileMetadata)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=400, detail="Invalid fileMetadata format")

        # Create upload directory
        upload_base_dir = Path(tempfile.gettempdir()) / "maru_lang_uploads"
        upload_dir = upload_base_dir / group_name

        print(f"📤 Uploading file: {file.filename}")

        # Save uploaded file and create FileInfo object
        file_info = await save_uploaded_file(file, file_meta, upload_dir)
        print(f"file_info: {file_info}")

        print(f"✅ Uploaded file: {file.filename}")

        # Start ingestion
        print(f"🔄 Starting ingestion for {group_name}")
        print(f"maruSync: {maruSync}")

        # Create and run IngestPipeline with FileInfo object
        pipeline = create_ingest_pipeline(
            upload_path=Path(folderPath),
            group_name=group_name,
            manager_id=user.id,
            re_embed=False,
            description=description,
            files=[file_info],  # Single file wrapped in list
            user_id=user.id if maruSync else None,
        )

        # Run IngestPipeline and collect result
        result = None
        async for item in pipeline.run():
            if isinstance(item, PipelineMessage):
                # Log progress messages
                print(f"[{item.message_type.value}] {item.message}")
            # elif isinstance(item, PipelineComplete):
            #     result = item.data

        # Set permissions if userGroupIds provided
        permission_message = None
        if result and result.group and user_group_id_list:
            try:
                perm_result = await set_user_group_permissions(
                    document_group=result.group,
                    user_group_ids=user_group_id_list,
                    replace=True
                )
                message_parts = []
                if perm_result["deleted"] > 0:
                    message_parts.append(f"{perm_result['deleted']} deleted")
                if perm_result["created"] > 0:
                    message_parts.append(f"{perm_result['created']} created")
                permission_message = f"Set permissions for {len(user_group_id_list)} user groups ({', '.join(message_parts)})"
                print(f"✓ {permission_message}")
            except Exception as e:
                permission_message = f"Error setting user group permissions: {str(e)}"
                print(f"⚠️ {permission_message}")

        # Return result
        if result is None:
            raise HTTPException(
                status_code=500, detail="Ingestion pipeline did not return result")

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
                "permissionMessage": permission_message,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Upload/Ingest error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up uploaded files
        if upload_dir and upload_dir.exists():
            try:
                shutil.rmtree(upload_dir)
                print(f"🗑️  Cleaned up upload directory: {upload_dir}")
            except Exception as e:
                print(f"⚠️  Failed to clean up {upload_dir}: {str(e)}")


@router.get("/managed-groups")
async def get_my_managed_document_groups(
    user: User = Depends(get_user_with_role(UserRoleCode.EDITOR))
):
    """
    Get all document groups where the current user is the manager.

    Returns document groups with statistics including:
    - Group ID and name
    - Base path
    - Description
    - Document count
    - Created timestamp

    Args:
        user: Authenticated user

    Returns:
        List of managed document groups with statistics
    """
    try:
        managed_groups = await get_managed_document_groups_with_stats(user.id)

        return {
            "success": True,
            "message": f"총 {len(managed_groups)}개의 문서 그룹을 관리하고 있습니다.",
            "data": {
                "groups": managed_groups,
                "total": len(managed_groups)
            }
        }

    except Exception as e:
        print(f"❌ Error fetching managed document groups: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
