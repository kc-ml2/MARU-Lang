"""
Ingest Pipeline dependency
"""
from pathlib import Path
from typing import Optional
from maru_lang.pipelines.ingest.pipeline import IngestPipeline
from maru_lang.core.vector_db.factory import get_vector_db
from maru_lang.models.vector_db import get_vector_db_config_from_settings
from maru_lang.configs.system_config import get_system_config
from maru_lang.configs import get_config_manager

config = get_system_config()


def create_ingest_pipeline(
    upload_path: Path,
    group_name: str,
    manager_id: int,
    re_embed: bool = False,
    all_files_list: Optional[list] = None,
    description: Optional[str] = None,
) -> IngestPipeline:
    """
    Create IngestPipeline instance for file ingestion.

    Args:
        upload_path: Path to uploaded files directory
        group_name: Document group name (usually folder name)
        manager_id: User ID who manages this group
        re_embed: Whether to re-embed existing documents
        all_files_list: Complete list of all file paths (for batch upload deletion detection)
        description: DocumentGroup description (only for root group)

    Returns:
        IngestPipeline instance
    """
    # Get VectorDB config using proper conversion function
    vdb_config = get_vector_db_config_from_settings()

    # Create IngestPipeline with virtual_path
    # Use group_name as virtual_path to avoid re-embedding when temp directory changes
    # virtual_path: DB 저장용 가상 경로 (실제 파일은 upload_path에서 읽음)
    pipeline = IngestPipeline(
        path=upload_path,  # 실제 파일 작업용 (임시 디렉토리)
        group_name=group_name,
        vdb_config=vdb_config,
        manager_id=manager_id,
        max_batch_size_mb=1000,  # 1GB batch size
        re_embed=re_embed,
        virtual_path=Path(group_name),  # DB 저장용 가상 경로
        all_files_list=all_files_list,  # 전체 파일 목록 (배치 업로드 삭제 판단용)
        description=description,  # DocumentGroup 설명 (루트 그룹에만 저장됨)
    )

    return pipeline
