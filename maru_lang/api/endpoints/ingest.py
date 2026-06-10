"""Ingest API endpoints - upload, status, check, delete."""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Query

from maru_lang.constants import INGEST_TASK_NAME
from maru_lang.enums.auth import UserRoleCode
from maru_lang.enums.documents import DocumentStatus, AuditAction

logger = logging.getLogger(__name__)
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
    request: Request,
    file: UploadFile = File(...),
    team_id: int = Form(...),
    folder_path: str = Form(""),
    mtime: float = Form(..., description="Original file modification time (unix timestamp)"),
    user: User = Depends(get_user_with_role(UserRoleCode.EDITOR)),
):
    """Upload a file and ingest it.

    When the task queue is on (app.state.arq present), embedding is enqueued to
    an ARQ worker and the response returns immediately (status "queued").
    Otherwise embedding runs in-process and the response waits for it, so the
    caller gets the real outcome ("active" / "error") instead of fire-and-forget.
    """
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

    arq = getattr(request.app.state, "arq", None)
    error: str | None = None
    if arq is not None:
        await arq.enqueue_job(INGEST_TASK_NAME, doc.id, team_id)
        status = "queued"
    else:
        # In-process + synchronous: the response reflects the embedding result,
        # and sequential uploads embed one-at-a-time (no pile-up). The document
        # is already marked ERROR + audited inside run_ingest_for_document.
        try:
            await run_ingest_for_document(doc, team_id)
            status = "active"
        except Exception as e:
            status = "error"
            error = str(e)

    return UploadResponse(
        document_id=doc.id,
        name=doc.name,
        status=status,
        is_reupload=is_reupload,
        error=error,
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
        folder_path = str(Path(doc.file_path).parent) if doc.file_path else None
        items.append(
            DocumentStatusItem(
                id=doc.id,
                name=doc.name,
                status=DocumentStatus(doc.status).name.lower(),
                folder_path=folder_path,
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
