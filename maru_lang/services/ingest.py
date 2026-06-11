"""Ingest service - file upload, status, change detection, and deletion."""
import logging
from pathlib import Path
from typing import Optional

from maru_lang.core.relation_db.models.documents import (
    Document,
    DocumentAuditLog,
)
from maru_lang.enums.documents import DocumentStatus, AuditAction
from maru_lang.services.document import get_or_create_upload_group, mark_deleting
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
    group = await get_or_create_upload_group(team_id, folder_path)

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

        if result.get("cancelled"):
            # A delete landed mid-ingest — ensure chunks + row are gone (the
            # graph already marked it DELETING). No success/error audit.
            await finalize_document_deletion(doc.id)
            return

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
        # The graph set ERROR atomically (fail_processing won't resurrect a
        # DELETING doc); here we only audit, and skip if it was deleted.
        if await Document.exists(id=doc.id):
            await _record_audit(
                document_id=doc.id,
                document_name=doc.name,
                team_id=team_id,
                action=AuditAction.INGEST_ERROR,
                detail={"error": str(e)},
            )
        raise


async def get_team_documents(team_id: int, group_id: Optional[int] = None) -> list[Document]:
    """Get a team's documents, newest first; optionally scoped to one folder.

    group_id is intersected with the team filter, so a group belonging to
    another team simply yields an empty list (no cross-team leak).
    """
    query = Document.filter(group__team_id=team_id)
    if group_id is not None:
        query = query.filter(group_id=group_id)
    return await query.order_by("-created_at").all()


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

    # Record the user's intent up front (before any state change).
    await _record_audit(
        document_id=doc.id,
        document_name=doc.name,
        team_id=team_id,
        user_id=user_id,
        action=AuditAction.DELETE,
    )

    # If the doc is mid-ingest (UPLOADING/PROCESSING), don't hard-delete — that
    # races the worker's chunk writes. Atomically mark DELETING; the worker
    # finalizes at its next checkpoint, and reconcile_deletions is the crash
    # backstop. mark_deleting returns False for terminal states → finalize now.
    if await mark_deleting(document_id):
        return
    await finalize_document_deletion(document_id)


async def finalize_document_deletion(document_id: str) -> None:
    """Physically remove a document's vector chunks and DB row (idempotent)."""
    try:
        get_vector_db().delete_all_chunks_by_document_id(document_id)
    except Exception as e:
        logger.warning(f"VectorDB chunk deletion failed for {document_id}: {e}")
    await Document.filter(id=document_id).delete()


async def retry_document(document_id: str, team_id: int, force: bool = False) -> Document:
    """Reset one document for re-ingest and return it (caller enqueues/runs).

    - Default: ERROR documents only (failed parse/embed).
    - force=True: ACTIVE too — full re-parse/re-embed, e.g. after a parser change.
    In-flight (UPLOADING/PROCESSING), DELETING, and INACTIVE (deliberately
    disabled) documents are never retried.

    The doc is reset to UPLOADING with error_message cleared, so the ingest
    graph's begin_processing can claim it again.

    Raises:
        LookupError: Document not found in this team.
        ValueError: Document is not in a retryable state.
    """
    doc = await Document.get_or_none(id=document_id, group__team_id=team_id)
    if doc is None:
        raise LookupError("Document not found")

    allowed = {DocumentStatus.ERROR} | ({DocumentStatus.ACTIVE} if force else set())
    if doc.status not in allowed:
        raise ValueError(
            f"Document is {DocumentStatus(doc.status).name}, not retryable "
            f"({'ERROR/ACTIVE' if force else 'ERROR only — use force for ACTIVE'})."
        )

    doc.status = DocumentStatus.UPLOADING
    doc.error_message = None
    await doc.save()
    return doc


async def reconcile_deletions() -> int:
    """Finalize documents stuck in DELETING (worker missed them or crashed).

    Run on worker startup as the backstop for the cooperative-cancel state
    machine. Returns the number of documents finalized.
    """
    stuck = await Document.filter(status=DocumentStatus.DELETING).all()
    for doc in stuck:
        await finalize_document_deletion(doc.id)
    if stuck:
        logger.info("reconcile_deletions: finalized %d DELETING document(s)", len(stuck))
    return len(stuck)


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


