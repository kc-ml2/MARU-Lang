"""
Ingest service functions for file upload and synchronization
"""
from typing import List
from datetime import datetime
from maru_lang.core.relation_db.models.documents import Document, DocumentGroup
from maru_lang.utils.document import make_source_fingerprint_for_file


async def check_files_to_upload(
    files: List[dict]  # [{"fileName": str, "createdAt": datetime, "absolutePath": str, "size": int}]
) -> List[str]:
    """
    Check which files need to be uploaded by comparing with database.

    Uses absolute path for document identification.

    Args:
        files: List of file information dicts with fileName, createdAt, absolutePath, size

    Returns:
        List of absolutePaths that need to be uploaded
    """
    files_to_upload = []

    for file_info in files:
        absolute_path = file_info["absolutePath"]
        created_at = file_info["createdAt"]
        file_size = file_info.get("size", 0)

        # Convert datetime to nanoseconds timestamp
        if isinstance(created_at, datetime):
            mtime_ns = int(created_at.timestamp() * 1e9)
        else:
            mtime_ns = int(created_at)

        # Generate expected fingerprint
        expected_fingerprint = make_source_fingerprint_for_file(
            absolute_path, file_size, mtime_ns
        )

        # Check if document exists with this path
        existing_doc = await Document.filter(file_path=absolute_path).first()

        if not existing_doc:
            # New file - needs upload
            files_to_upload.append(absolute_path)
            continue

        # Compare fingerprint
        if existing_doc.source_fingerprint != expected_fingerprint:
            # File modified - needs re-upload
            files_to_upload.append(absolute_path)
            continue

        # File exists and unchanged - skip

    return files_to_upload
