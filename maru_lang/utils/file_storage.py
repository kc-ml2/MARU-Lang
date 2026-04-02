"""File storage utilities - save and retrieve original files."""
import shutil
from pathlib import Path
from typing import BinaryIO

from maru_lang.configs import get_config


def get_storage_dir() -> Path:
    """Get the absolute storage directory from config."""
    cfg = get_config()
    p = Path(cfg.storage_dir)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p


def get_document_dir(team_id: int, doc_id: str) -> Path:
    """Get the storage directory for a specific document."""
    return get_storage_dir() / str(team_id) / doc_id


def save_file(source: Path, team_id: int, doc_id: str) -> str:
    """Copy a local file to permanent storage.

    Args:
        source: Source file path.
        team_id: Team ID.
        doc_id: Document ID.

    Returns:
        Absolute path to the stored file.
    """
    dest_dir = get_document_dir(team_id, doc_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"original{source.suffix}"
    shutil.copy2(source, dest)
    return str(dest.absolute())


async def save_upload(upload_file: BinaryIO, filename: str, team_id: int, doc_id: str) -> str:
    """Save an uploaded file (from FastAPI UploadFile) to permanent storage.

    Args:
        upload_file: File-like object to read from.
        filename: Original filename (for extension).
        team_id: Team ID.
        doc_id: Document ID.

    Returns:
        Absolute path to the stored file.
    """
    ext = Path(filename).suffix
    dest_dir = get_document_dir(team_id, doc_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"original{ext}"

    with open(dest, "wb") as f:
        while chunk := upload_file.read(8192):
            f.write(chunk)

    return str(dest.absolute())
