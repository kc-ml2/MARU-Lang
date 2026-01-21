"""
Ingest Pipeline dependency
"""
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from maru_lang.pipelines.ingest import IngestPipeline, MaruSyncIngestPipeline
from maru_lang.models.vector_db import get_vector_db_config_from_settings
from maru_lang.configs.system_config import get_system_config
from maru_lang.schemas.ingest import FileInfo
from maru_lang.utils.file_scanner import scan_directory

config = get_system_config()


def create_ingest_pipeline(
    upload_path: Path,
    group_name: str,
    manager_id: int,
    re_embed: bool = False,
    description: Optional[str] = None,
    files: Optional[List[FileInfo]] = None,
    user_id: int = None,
    dry_run: bool = False,
) -> IngestPipeline:
    """
    Create IngestPipeline instance for file ingestion.

    Args:
        upload_path: Path to uploaded files directory (used as base_path for DB storage)
        group_name: Document group name (usually folder name)
        manager_id: User ID who manages this group
        re_embed: Whether to re-embed existing documents
        description: DocumentGroup description (only for root group)
        files: Optional pre-scanned file list. If None, will scan upload_path
        user_id: User ID who is ingesting the files
    Returns:
        IngestPipeline
    """

    # Scan upload_path if file list is not provided
    if files is None:
        file_paths = scan_directory(upload_path, recursive=True)
        files = [FileInfo(
            fileName=file_path.name,
            createdAt=datetime.fromtimestamp(file_path.stat().st_ctime),
            relativePath=file_path.relative_to(upload_path).as_posix(),
            size=file_path.stat().st_size
        ) for file_path in file_paths]

    if user_id:
        pipeline = MaruSyncIngestPipeline(
            files=files,
            group_name=group_name,
            manager_id=manager_id,
            base_path=upload_path,
            user_id=user_id,
        )
    else:
        pipeline = IngestPipeline(
            files=files,
            group_name=group_name,
            vdb_config=get_vector_db_config_from_settings(),
            manager_id=manager_id,
            # base_path for DocumentGroup (for DB storage)
            base_path=upload_path,
            re_embed=re_embed,
            # DocumentGroup description (only saved for root group)
            description=description,
        )

    return pipeline
