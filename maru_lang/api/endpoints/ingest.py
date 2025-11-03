import os
import json
import shutil
import tempfile
from pathlib import Path
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from maru_lang.enums.auth import UserRoleCode
from maru_lang.dependencies.auth import get_user_with_role, User
from maru_lang.dependencies.ingest import create_ingest_pipeline
from maru_lang.pipelines.base import PipelineMessage, PipelineComplete
from maru_lang.schemas.ingest import (
    SyncCheckRequest,
    SyncCheckResponse,
    SyncUploadResponse,
)
from maru_lang.services.ingest import check_files_to_upload, get_or_create_document_group
from maru_lang.services.document import set_user_group_permissions, get_managed_document_groups_with_stats
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
        # Create group name with user identifier: {username}/{folderPath}
        group_name = f"{user.email.split('@')[0]}/{request.folderPath}"

        # Convert FileInfo objects to dict format for service function
        files_data = [
            {
                "fileName": file_info.fileName,
                "createdAt": file_info.createdAt,
                "relativePath": file_info.relativePath,
                "size": file_info.size
            }
            for file_info in request.files
        ]

        # Check which files need to be uploaded (using user-scoped group name)
        files_to_upload = await check_files_to_upload(
            folder_path=group_name,  # Use {username}/{folderPath}
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


@router.post("/sync/upload")
async def upload_and_ingest(
    folderPath: str = Form(..., description="프로젝트 폴더명"),
    files: List[UploadFile] = File(..., description="업로드할 파일 배열 (현재 배치)"),
    fileMetadata: str = Form(None, description="파일 메타데이터 (JSON 배열: [{fileName, createdAt, relativePath, size}])"),
    allFilesList: str = Form(None, description="전체 파일 목록 (JSON 배열: [relativePath, ...]) - 배치 업로드 시 삭제 판단용"),
    userGroupIds: str = Form(None, description="사용자 그룹 ID 목록 (JSON 배열 문자열)"),
    description: str = Form(None, description="DocumentGroup 설명"),
    user: User = Depends(get_user_with_role(UserRoleCode.EDITOR))
):
    """
    Upload files and process them with IngestPipeline.

    Batch Upload Support:
    - Client can send files in batches (e.g., 100 files per batch)
    - allFilesList should contain the complete file list across all batches
    - This prevents IngestPipeline from deleting files from previous batches
    - Fingerprint-based deduplication automatically skips already processed files

    Processing:
    - Files are uploaded and immediately processed by IngestPipeline
    - SSE stream provides real-time progress

    Returns SSE stream with the following events:
    - upload_started: Upload started
    - upload_progress: File upload progress
    - ingest_started: Ingestion started
    - ingest_progress: Ingestion progress messages (info, warning, error)
    - ingest_completed: Ingestion completed
    - error: Unrecoverable error

    Args:
        folderPath: Project folder name (used as document group name)
        files: Files to upload (current batch)
        fileMetadata: JSON string of file metadata array (current batch)
        allFilesList: JSON string of all file paths (across all batches) for deletion detection
        userGroupIds: JSON string of user group IDs
        user: Authenticated user

    Returns:
        SSE stream with real-time progress
    """
    async def event_generator():
        """Generate SSE events for upload and ingestion"""
        upload_dir = None
        try:
            # Parse userGroupIds from JSON string
            user_group_id_list = []
            if userGroupIds:
                try:
                    user_group_id_list = json.loads(userGroupIds)
                except json.JSONDecodeError:
                    error_event = {
                        "type": "error",
                        "data": {"message": "Invalid userGroupIds format"}
                    }
                    yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
                    return
            # Parse fileMetadata from JSON string
            file_metadata_map = {}
            if fileMetadata:
                try:
                    metadata_list = json.loads(fileMetadata)
                    # Create map: relativePath -> createdAt
                    file_metadata_map = {
                        item["relativePath"]: item["createdAt"]
                        for item in metadata_list
                    }
                except (json.JSONDecodeError, KeyError) as e:
                    error_event = {
                        "type": "error",
                        "data": {"message": f"Invalid fileMetadata format: {str(e)}"}
                    }
                    yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
                    return

            # Parse allFilesList from JSON string (for batch upload deletion detection)
            all_files_list = []
            if allFilesList:
                try:
                    all_files_list = json.loads(allFilesList)
                except json.JSONDecodeError as e:
                    error_event = {
                        "type": "error",
                        "data": {"message": f"Invalid allFilesList format: {str(e)}"}
                    }
                    yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
                    return

            # Create group name with user identifier: {username}/{folderPath}
            group_name = f"{user.email.split('@')[0]}/{folderPath}"

            # Create upload directory
            upload_base_dir = Path(tempfile.gettempdir()) / "maru_lang_uploads"
            upload_dir = upload_base_dir / group_name
            upload_dir.mkdir(parents=True, exist_ok=True)

            # Send upload started event
            upload_start_event = {
                "type": "upload_started",
                "data": {
                    "folderPath": folderPath,
                    "groupName": group_name,
                    "totalFiles": len(files),
                    "message": f"{len(files)}개 파일 업로드 시작..."
                }
            }
            yield f"data: {json.dumps(upload_start_event, ensure_ascii=False)}\n\n"

            # Upload files
            uploaded_count = 0
            for idx, uploaded_file in enumerate(files):
                try:
                    filename = uploaded_file.filename
                    if not filename:
                        continue

                    # Save file
                    file_path = upload_dir / filename
                    file_path.parent.mkdir(parents=True, exist_ok=True)

                    content = await uploaded_file.read()
                    with open(file_path, "wb") as f:
                        f.write(content)

                    # Set original mtime if provided
                    if filename in file_metadata_map:
                        from datetime import datetime
                        created_at_str = file_metadata_map[filename]
                        # Parse ISO format datetime
                        created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                        timestamp = created_at.timestamp()
                        # Set both atime and mtime to original created time
                        os.utime(file_path, (timestamp, timestamp))

                    uploaded_count += 1

                    # Send progress event
                    progress_event = {
                        "type": "upload_progress",
                        "data": {
                            "filename": filename,
                            "current": idx + 1,
                            "total": len(files),
                            "size": len(content)
                        }
                    }
                    yield f"data: {json.dumps(progress_event, ensure_ascii=False)}\n\n"

                except Exception as e:
                    error_event = {
                        "type": "upload_error",
                        "data": {
                            "filename": uploaded_file.filename,
                            "error": str(e)
                        }
                    }
                    yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

            # Upload completed
            upload_complete_event = {
                "type": "upload_completed",
                "data": {
                    "uploadedCount": uploaded_count,
                    "totalFiles": len(files),
                    "message": f"{uploaded_count}개 파일 업로드 완료"
                }
            }
            yield f"data: {json.dumps(upload_complete_event, ensure_ascii=False)}\n\n"

            # Start ingestion
            ingest_start_event = {
                "type": "ingest_started",
                "data": {
                    "folderPath": folderPath,
                    "groupName": group_name,
                    "uploadDir": str(upload_dir),
                    "message": "문서 처리를 시작합니다..."
                }
            }
            yield f"data: {json.dumps(ingest_start_event, ensure_ascii=False)}\n\n"

            # Create and run IngestPipeline with user-scoped group name
            pipeline = create_ingest_pipeline(
                upload_path=upload_dir,
                group_name=group_name,  # Use {username}/{folderPath}
                manager_id=user.id,
                re_embed=False,
                all_files_list=all_files_list if all_files_list else None,
                description=description,  # DocumentGroup 설명
            )

            # Stream IngestPipeline progress
            async for item in pipeline.run():
                if isinstance(item, PipelineMessage):
                    # Progress message
                    message_event = {
                        "type": "ingest_progress",
                        "data": {
                            "level": item.message_type.value,
                            "message": item.message,
                            "data": item.data
                        }
                    }
                    yield f"data: {json.dumps(message_event, ensure_ascii=False)}\n\n"

                elif isinstance(item, PipelineComplete):
                    # Ingestion completed
                    result = item.data
                    # Set permissions if userGroupIds provided
                    if result and user_group_id_list:
                        try:
                            # Get the DocumentGroup that was created/updated
                            document_group = result.group
                            # Set permissions using service function (replace mode)
                            perm_result = await set_user_group_permissions(
                                document_group=document_group,
                                user_group_ids=user_group_id_list,
                                replace=True  # 기존 권한 삭제 후 새로 설정
                            )
                            # Send permission setup event
                            message_parts = []
                            if perm_result["deleted"] > 0:
                                message_parts.append(f"{perm_result['deleted']}개 기존 권한 삭제")
                            if perm_result["created"] > 0:
                                message_parts.append(f"{perm_result['created']}개 권한 생성")
                            permission_event = {
                                "type": "ingest_progress",
                                "data": {
                                    "level": "info",
                                    "message": f"✓ {len(user_group_id_list)}개 사용자 그룹에 권한 설정 완료 ({', '.join(message_parts)})",
                                    "data": None
                                }
                            }
                            yield f"data: {json.dumps(permission_event, ensure_ascii=False)}\n\n"
                        except Exception as e:
                            error_event = {
                                "type": "ingest_progress",
                                "data": {
                                    "level": "warning",
                                    "message": f"⚠️ 권한 설정 실패: {str(e)}",
                                    "data": None
                                }
                            }
                            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

                    complete_event = {
                        "type": "ingest_completed",
                        "data": {
                            "success": result is not None,
                            "totalFiles": result.total_files if result else 0,
                            "processedFiles": result.processed_files if result else 0,
                            "skippedFiles": result.skipped_files if result else 0,
                            "failedFiles": result.failed_files if result else 0,
                            "failedDetails": result.failed_details if result else None,
                            "message": "문서 처리가 완료되었습니다."
                        }
                    }
                    yield f"data: {json.dumps(complete_event, ensure_ascii=False)}\n\n"

        except Exception as e:
            print(f"❌ Upload/Ingest error: {str(e)}")
            error_event = {
                "type": "error",
                "data": {
                    "message": str(e)
                }
            }
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

            # Send ingest_completed event even on failure so client can finish processing
            failure_complete_event = {
                "type": "ingest_completed",
                "data": {
                    "success": False,
                    "totalFiles": 0,
                    "processedFiles": 0,
                    "skippedFiles": 0,
                    "failedFiles": 0,
                    "failedDetails": None,
                    "message": f"문서 처리 중 오류가 발생했습니다: {str(e)}"
                }
            }
            yield f"data: {json.dumps(failure_complete_event, ensure_ascii=False)}\n\n"

        finally:
            # Clean up uploaded files
            if upload_dir and upload_dir.exists():
                try:
                    shutil.rmtree(upload_dir)
                    print(f"🗑️  Cleaned up upload directory: {upload_dir}")
                except Exception as e:
                    print(f"⚠️  Failed to clean up {upload_dir}: {str(e)}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


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
