"""Ingest service - file upload, status, and change detection."""
import logging
from pathlib import Path

from maru_lang.core.relation_db.models.documents import Document, DocumentGroup
from maru_lang.enums.documents import DocumentStatus
from maru_lang.schemas.ingest import FileInfo
from maru_lang.services.document import get_or_create_document_group
from maru_lang.utils.document import new_ulid, make_source_fingerprint_for_file
from maru_lang.utils.file_storage import save_upload
from maru_lang.graph.ingest import run_ingest

logger = logging.getLogger(__name__)


async def upload_and_ingest(
    file_obj,
    filename: str,
    file_size: int,
    team_id: int,
    folder_path: str = "",
    mtime: float = 0.0,
) -> Document:
    """Save uploaded file, create DB record.

    Args:
        file_obj: File-like object to read from.
        filename: Original filename.
        file_size: File size in bytes.
        team_id: Team ID.
        folder_path: Optional folder path for group hierarchy.
        mtime: Original file modification time (unix timestamp from client).

    Returns:
        Created Document with status=UPLOADING.
    """
    doc_id = new_ulid()

    # Save to permanent storage
    storage_path = await save_upload(file_obj, filename, team_id, doc_id)

    # Get or create root group for team
    group = await _get_or_create_upload_group(team_id)

    # Fingerprint uses client-provided mtime so check() can match
    abs_path = str(Path(folder_path) / filename) if folder_path else filename
    fingerprint = make_source_fingerprint_for_file(
        file_path=abs_path,
        size=file_size,
        mtime_ns=int(mtime * 1e9),
    )
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

    return doc


async def run_ingest_for_document(doc: Document, team_id: int) -> None:
    """Run ingest pipeline for a document. Updates status on completion/error.

    Intended for use in BackgroundTasks.
    """
    try:
        file_info = FileInfo(
            fileName=doc.metadata.get("original_filename", doc.name),
            createdAt=doc.created_at,
            absolutePath=doc.file_path or "",
            size=doc.file_size or 0,
            tempFilePath=doc.storage_path,
        )

        await run_ingest(file=file_info, team_id=team_id)

    except Exception as e:
        logger.error(f"Ingest failed for {doc.id}: {e}")
        doc.status = DocumentStatus.ERROR
        doc.error_message = str(e)
        await doc.save()


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


async def _get_or_create_upload_group(team_id: int) -> DocumentGroup:
    """Get or create a root 'uploads' group for the team."""
    group, _ = await get_or_create_document_group(
        team_id=team_id, name="uploads", parent=None,
    )
    return group
