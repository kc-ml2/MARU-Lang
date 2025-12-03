"""
File upload utilities
"""
import os
from pathlib import Path
from datetime import datetime
from typing import List
from fastapi import UploadFile

from maru_lang.schemas.ingest import FileInfo


async def save_uploaded_file(
    uploaded_file: UploadFile,
    file_meta: dict,
    upload_dir: Path
) -> FileInfo:
    """
    Save a single uploaded file to temporary directory and create FileInfo object.

    Args:
        uploaded_file: Uploaded file from FastAPI
        file_meta: File metadata dict {fileName, createdAt, relativePath, size}
        upload_dir: Directory to save file to

    Returns:
        FileInfo object with tempFilePath set

    Raises:
        Exception: If file upload fails
    """
    # Create upload directory
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = uploaded_file.filename
    if not filename:
        raise ValueError("Filename is empty")

    # Determine save path based on relativePath
    relative_path = file_meta.get("relativePath", filename)
    file_path = upload_dir / relative_path
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Save file content
    content = await uploaded_file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    # Set original mtime if provided
    created_at_str = file_meta.get("createdAt")
    if created_at_str:
        try:
            # Parse ISO format datetime
            created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
            timestamp = created_at.timestamp()
            # Set both atime and mtime to original created time
            os.utime(file_path, (timestamp, timestamp))
        except Exception as e:
            print(f"⚠️  Failed to set mtime for {filename}: {str(e)}")

    # Create FileInfo with tempFilePath
    file_info = FileInfo(
        fileName=file_meta["fileName"],
        createdAt=datetime.fromisoformat(created_at_str.replace('Z', '+00:00')) if created_at_str else datetime.now(),
        relativePath=relative_path,  # Use the relative_path variable we already determined
        size=file_meta.get("size", len(content)),
        tempFilePath=str(file_path.absolute())
    )

    return file_info


async def save_uploaded_files(
    uploaded_files: List[UploadFile],
    file_metadata: List[dict],
    upload_dir: Path
) -> tuple[List[FileInfo], List[str]]:
    """
    Save uploaded files to temporary directory and create FileInfo objects.

    Args:
        uploaded_files: List of uploaded files from FastAPI
        file_metadata: List of file metadata dicts [{fileName, createdAt, relativePath, size}]
        upload_dir: Directory to save files to

    Returns:
        tuple: (file_infos, upload_errors)
            - file_infos: List of FileInfo objects with tempFilePath set
            - upload_errors: List of error messages for failed uploads
    """
    # Create metadata map for quick lookup
    metadata_map = {meta["fileName"]: meta for meta in file_metadata}

    file_infos = []
    upload_errors = []

    for uploaded_file in uploaded_files:
        try:
            filename = uploaded_file.filename
            if not filename:
                continue

            # Get metadata for this file
            if filename not in metadata_map:
                upload_errors.append(f"{filename}: No metadata found")
                continue

            meta = metadata_map[filename]

            # Use single file upload function
            file_info = await save_uploaded_file(uploaded_file, meta, upload_dir)
            file_infos.append(file_info)

        except Exception as e:
            upload_errors.append(f"{uploaded_file.filename}: {str(e)}")

    return file_infos, upload_errors
