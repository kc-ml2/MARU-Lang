"""Ingest service - file upload, status, change detection, and deletion."""
import logging
from pathlib import Path
from typing import Optional

from maru_lang.core.relation_db.models.documents import (
    Document,
    DocumentGroup,
    DocumentAuditLog,
)
from maru_lang.enums.documents import DocumentStatus, AuditAction
from maru_lang.services.document import get_or_create_document_group
from maru_lang.utils.document import new_ulid, make_source_fingerprint_for_file
from maru_lang.utils.file_storage import save_upload
from maru_lang.graph.ingest.graph import get_ingest_graph
from maru_lang.graph.ingest.state import build_ingest_input
from maru_lang.core.vector_db import get_vector_db

logger = logging.getLogger(__name__)


async def upload_and_ingest(
    file_obj,
    filename: str,
    file_size: int,
    team_id: int,
    folder_path: str = "",
    mtime: float = 0.0,
    user_id: Optional[int] = None,
) -> tuple[Document, bool]:
    """Save uploaded file, create or update DB record.

    Args:
        file_obj: File-like object to read from.
        filename: Original filename.
        file_size: File size in bytes.
        team_id: Team ID.
        folder_path: Optional folder path for group hierarchy.
        mtime: Original file modification time (unix timestamp from client).
        user_id: ID of the user performing the upload.

    Returns:
        Tuple of (Document, is_reupload).
    """
    doc_id = new_ulid()

    # Save to permanent storage
    storage_path = await save_upload(file_obj, filename, team_id, doc_id)

    # Get or create group named after the uploaded folder
    group = await _get_or_create_upload_group(team_id, folder_path)

    # Fingerprint uses client-provided mtime so check() can match
    abs_path = str(Path(folder_path) / filename) if folder_path else filename
    fingerprint = make_source_fingerprint_for_file(
        file_path=abs_path,
        size=file_size,
        mtime_ns=int(mtime * 1e9),
    )

    # Check for existing document with same fingerprint
    existing = await Document.filter(source_fingerprint=fingerprint).first()
    if existing:
        existing.storage_path = storage_path
        existing.status = DocumentStatus.UPLOADING
        existing.error_message = None
        await existing.save()

        await _record_audit(
            document_id=existing.id,
            document_name=existing.name,
            team_id=team_id,
            user_id=user_id,
            action=AuditAction.RE_UPLOAD,
        )
        return existing, True

    doc = await Document.create(
        id=doc_id,
        name=Path(filename).stem,
        group=group,
        file_path=abs_path,
        storage_path=storage_path,
        file_size=file_size,
        source_fingerprint=fingerprint,
        status=DocumentStatus.UPLOADING,
        metadata={"original_filename": filename},
    )

    await _record_audit(
        document_id=doc.id,
        document_name=doc.name,
        team_id=team_id,
        user_id=user_id,
        action=AuditAction.UPLOAD,
    )
    return doc, False


async def run_ingest_for_document(doc: Document, team_id: int) -> None:
    """Run the ingest graph for an already-synced (API-uploaded) document.

    The Document record and group already exist (created by upload_and_ingest),
    so the graph's sync_document step passes through and only parse + embedding
    run — the same compiled graph the CLI sync path uses.
    """
    state = build_ingest_input(
        team_id,
        document={
            "id": doc.id,
            "name": doc.name,
            "file_path": doc.file_path,
            "storage_path": doc.storage_path,
            "group_id": doc.group_id,
            "metadata": doc.metadata,
        },
        needs_processing=True,
    )

    try:
        result = await get_ingest_graph().ainvoke(state)

        if result.get("error"):
            raise RuntimeError(result["error"])

        await _record_audit(
            document_id=doc.id,
            document_name=doc.name,
            team_id=team_id,
            action=AuditAction.INGEST_SUCCESS,
        )

    except Exception as e:
        logger.error(f"Ingest failed for {doc.id}: {e}")

        # 삭제된 문서에 에러 상태를 쓰면 레코드가 되살아날 수 있으므로 존재 확인
        if await Document.exists(id=doc.id):
            doc.status = DocumentStatus.ERROR
            doc.error_message = str(e)
            await doc.save()

        await _record_audit(
            document_id=doc.id,
            document_name=doc.name,
            team_id=team_id,
            action=AuditAction.INGEST_ERROR,
            detail={"error": str(e)},
        )
        raise


async def get_team_documents(team_id: int) -> list[Document]:
    """Get all documents for a team, ordered by newest first."""
    return await Document.filter(
        group__team_id=team_id,
    ).order_by("-created_at").all()


async def check_files_to_upload(
    files: list[dict],
) -> list[int]:
    """Check which files need uploading by fingerprint comparison.

    Args:
        files: List of dicts with absolutePath, size, mtime.

    Returns:
        List of indices that need uploading.
    """
    indices = []
    for i, f in enumerate(files):
        fingerprint = make_source_fingerprint_for_file(
            file_path=f["absolutePath"],
            size=f["size"],
            mtime_ns=int(f["mtime"] * 1e9),
        )
        existing = await Document.filter(source_fingerprint=fingerprint).first()
        if existing is None:
            indices.append(i)

    return indices


async def delete_document_by_id(
    document_id: str,
    team_id: int,
    user_id: int,
) -> None:
    """Delete a document from VectorDB and RDB, recording audit log.

    Raises:
        ValueError: If document not found or doesn't belong to the team.
    """
    doc = await Document.get_or_none(id=document_id, group__team_id=team_id)
    if not doc:
        raise ValueError("Document not found")

    # 1. VectorDB 청크 삭제
    try:
        vdb = get_vector_db()
        vdb.delete_all_chunks_by_document_id(document_id)
    except Exception as e:
        logger.warning(f"VectorDB chunk deletion failed for {document_id}: {e}")

    # 2. Audit log 기록 (삭제 전에 기록)
    await _record_audit(
        document_id=doc.id,
        document_name=doc.name,
        team_id=team_id,
        user_id=user_id,
        action=AuditAction.DELETE,
    )

    # 3. RDB 레코드 삭제
    await doc.delete()


async def get_audit_logs_for_documents(
    document_ids: list[str],
) -> dict[str, list[DocumentAuditLog]]:
    """Fetch audit logs grouped by document_id."""
    if not document_ids:
        return {}
    logs = await DocumentAuditLog.filter(
        document_id__in=document_ids,
    ).prefetch_related("user").all()

    result: dict[str, list[DocumentAuditLog]] = {}
    for log in logs:
        result.setdefault(log.document_id, []).append(log)
    return result


async def _record_audit(
    document_id: str,
    document_name: str,
    team_id: int,
    action: AuditAction,
    user_id: Optional[int] = None,
    detail: Optional[dict] = None,
) -> None:
    """Record a document audit log entry."""
    await DocumentAuditLog.create(
        document_id=document_id,
        document_name=document_name,
        team_id=team_id,
        user_id=user_id,
        action=action,
        detail=detail or {},
    )


async def _get_or_create_upload_group(
    team_id: int,
    folder_path: str = "",
) -> DocumentGroup:
    """Get or create a group named after the upload folder.

    Uses the last component of folder_path as the group name.
    Falls back to 'uploads' when folder_path is empty.
    """
    if folder_path:
        group_name = Path(folder_path).name
    else:
        group_name = "uploads"

    group, _ = await get_or_create_document_group(
        team_id=team_id, name=group_name, parent=None,
    )
    return group
