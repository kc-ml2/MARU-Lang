"""
Ingest service functions for file upload and synchronization
"""
from typing import List, Tuple
from datetime import datetime
from pathlib import Path
from maru_lang.core.relation_db.models.documents import Document, DocumentGroup
from maru_lang.utils.document import make_source_fingerprint_for_file


async def check_files_to_upload(
    folder_path: str,
    files: List[dict]  # [{"fileName": str, "createdAt": datetime, "relativePath": str}]
) -> List[str]:
    """
    Check which files need to be uploaded by comparing with database.

    Compares:
    - file_path (relativePath)
    - createdAt (mtime)
    - fileName

    Args:
        folder_path: Project folder name
        files: List of file information dicts

    Returns:
        List of relativePaths that need to be uploaded
    """
    files_to_upload = []

    for file_info in files:
        relative_path = file_info["relativePath"]
        file_name = file_info["fileName"]
        created_at = file_info["createdAt"]

        # Convert datetime to nanoseconds timestamp
        # For comparison, we'll use seconds * 1e9
        if isinstance(created_at, datetime):
            mtime_ns = int(created_at.timestamp() * 1e9)
        else:
            # If it's already a timestamp
            mtime_ns = int(created_at)

        # Check if document exists in database
        existing_doc = await Document.get_or_none(file_path=relative_path)

        if not existing_doc:
            # New file - needs upload
            files_to_upload.append(relative_path)
            continue

        # Compare fingerprint (we don't have file_size yet, so compare mtime)
        # In production, you might want to compare hash or size as well
        # For now, we'll assume if file_path exists and name matches, it's the same
        # This is simplified - you may want to add more sophisticated comparison

        # Extract mtime from existing document's source_fingerprint if available
        # source_fingerprint format: "{filename}:{size}:{mtime_ns}"
        if existing_doc.source_fingerprint:
            try:
                parts = existing_doc.source_fingerprint.split(":")
                if len(parts) == 3:
                    existing_mtime = int(parts[2])
                    if existing_mtime != mtime_ns:
                        # File modified - needs re-upload
                        files_to_upload.append(relative_path)
                        continue
            except (ValueError, IndexError):
                # Invalid fingerprint format - needs re-upload
                files_to_upload.append(relative_path)
                continue
        else:
            # No fingerprint - needs re-upload
            files_to_upload.append(relative_path)

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
