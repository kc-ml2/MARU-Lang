"""
Ingest service functions for file upload and synchronization
"""
from typing import List, Tuple
from datetime import datetime
from pathlib import Path
from maru_lang.core.relation_db.models.documents import Document, DocumentGroup, DocumentGroupMembership
from maru_lang.utils.document import make_source_fingerprint_for_file


async def check_files_to_upload(
    folder_path: str,
    files: List[dict]  # [{"fileName": str, "createdAt": datetime, "relativePath": str, "size": int}]
) -> List[str]:
    """
    Check which files need to be uploaded by comparing with database.

    Uses same logic as IngestPipeline's upsert_document_from_file:
    - Compares file_path (relativePath) within the DocumentGroup
    - Compares source_fingerprint (SHA256 hash of path|size|mtime)
    - Only checks files in the specified folder's DocumentGroup

    Args:
        folder_path: Project folder name (DocumentGroup name, e.g., "user/project")
        files: List of file information dicts with fileName, createdAt, relativePath, size

    Returns:
        List of relativePaths that need to be uploaded
    """
    files_to_upload = []

    # Check if DocumentGroup exists for this folder
    document_group = await DocumentGroup.get_or_none(name=folder_path)

    # If no group exists, all files are new
    if not document_group:
        return [file_info["relativePath"] for file_info in files]

    for file_info in files:
        relative_path = file_info["relativePath"]
        file_name = file_info["fileName"]
        created_at = file_info["createdAt"]
        file_size = file_info.get("size", 0)  # File size in bytes

        # Convert datetime to nanoseconds timestamp
        if isinstance(created_at, datetime):
            mtime_ns = int(created_at.timestamp() * 1e9)
        else:
            mtime_ns = int(created_at)

        # Generate expected fingerprint
        # Note: folder_path is already "{username}/{folderPath}"
        db_file_path = f"{folder_path}/{relative_path}"
        expected_fingerprint = make_source_fingerprint_for_file(
            db_file_path, file_size, mtime_ns
        )

        # Check if document exists in this specific group
        existing_doc = await Document.filter(
            file_path=db_file_path,
            group_memberships__group=document_group
        ).first()

        if not existing_doc:
            # New file in this group - needs upload
            files_to_upload.append(relative_path)
            continue

        # Compare fingerprint
        if existing_doc.source_fingerprint != expected_fingerprint:
            # File modified - needs re-upload
            files_to_upload.append(relative_path)
            continue

        # File exists and unchanged - skip

    return files_to_upload


async def get_or_create_document_group(
    folder_path: str,
    manager_id: int
) -> DocumentGroup:
    """
    Get or create a DocumentGroup for the uploaded folder.

    Args:
        folder_path: Project folder name
        manager_id: User ID who manages this group

    Returns:
        DocumentGroup instance
    """
    from maru_lang.services.document import upsert_document_group

    # Use folder_path as both name and base_path
    # In production, you might want to use absolute paths
    group = await upsert_document_group(
        name=folder_path,
        base_path=folder_path,
        manager_id=manager_id,
    )

    return group
