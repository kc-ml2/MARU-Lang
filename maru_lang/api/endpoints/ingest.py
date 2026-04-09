"""Ingest API endpoints - upload, status, check, delete."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form, Query

from maru_lang.enums.auth import UserRoleCode
from maru_lang.enums.documents import DocumentStatus, AuditAction
from maru_lang.dependencies.auth import get_user_with_role, User
from maru_lang.schemas.ingest import (
    UploadResponse,
    StatusResponse,
    DocumentStatusItem,
    AuditLogEntry,
    CheckRequest,
    CheckResponse,
    DeleteResponse,
)
from maru_lang.services.ingest import (
    upload_and_ingest,
    run_ingest_for_document,
    get_team_documents,
    check_files_to_upload,
    delete_document_by_id,
    get_audit_logs_for_documents,
)
from maru_lang.services.team import _check_admin

router = APIRouter(
    prefix="/ingest",
    tags=["Ingest"],
)


@router.post("/upload", response_model=UploadResponse)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    team_id: int = Form(...),
    folder_path: str = Form(""),
    mtime: float = Form(..., description="Original file modification time (unix timestamp)"),
    user: User = Depends(get_user_with_role(UserRoleCode.EDITOR)),
):
    """Upload a file and start background ingest."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    doc, is_reupload = await upload_and_ingest(
        file_obj=file.file,
        filename=file.filename,
        file_size=file.size or 0,
        team_id=team_id,
        folder_path=folder_path,
        mtime=mtime,
        user_id=user.id,
    )

    background_tasks.add_task(run_ingest_for_document, doc, team_id)

    return UploadResponse(
        document_id=doc.id,
        name=doc.name,
        status="uploading",
        is_reupload=is_reupload,
    )


@router.get("/status", response_model=StatusResponse)
async def get_status(
    team_id: int,
    user: User = Depends(get_user_with_role(UserRoleCode.EDITOR)),
):
    """Get document status for a team."""
    docs = await get_team_documents(team_id)

    # Fetch audit logs for all documents in one query
    doc_ids = [doc.id for doc in docs]
    audit_map = await get_audit_logs_for_documents(doc_ids)

    items = []
    for doc in docs:
        logs = audit_map.get(doc.id, [])
        audit_entries = [
            AuditLogEntry(
                action=AuditAction(log.action).name.lower(),
                user_name=log.user.name if log.user else None,
                detail=log.detail,
                created_at=log.created_at,
            )
            for log in logs
        ]
        items.append(
            DocumentStatusItem(
                id=doc.id,
                name=doc.name,
                status=DocumentStatus(doc.status).name.lower(),
                file_size=doc.file_size,
                created_at=doc.created_at,
                updated_at=doc.updated_at,
                error=doc.error_message,
                audit_logs=audit_entries,
            )
        )

    return StatusResponse(
        team_id=team_id,
        documents=items,
        total=len(items),
    )


@router.post("/check", response_model=CheckResponse)
async def check_files(
    request: CheckRequest,
    user: User = Depends(get_user_with_role(UserRoleCode.EDITOR)),
):
    """Check which files need to be uploaded."""
    files = [
        {"absolutePath": f.absolutePath, "size": f.size, "mtime": f.mtime}
        for f in request.files
    ]
    indices = await check_files_to_upload(files)

    return CheckResponse(
        indices_to_upload=indices,
        total=len(request.files),
    )


@router.delete("/{document_id}", response_model=DeleteResponse)
async def delete_document(
    document_id: str,
    team_id: int = Query(...),
    user: User = Depends(get_user_with_role(UserRoleCode.EDITOR)),
):
    """Delete a document and its embeddings. Requires team admin role."""
    try:
        await _check_admin(team_id, user)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    try:
        await delete_document_by_id(
            document_id=document_id,
            team_id=team_id,
            user_id=user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return DeleteResponse(document_id=document_id, deleted=True)
