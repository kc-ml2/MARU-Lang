from dataclasses import dataclass, field
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from maru_lang.core.relation_db.models.documents import Document, DocumentGroup


@dataclass(frozen=True)
class PipelineConfig:
    model_name: str
    model_dim: int
    normalize_ver: str
    pooling: str
    lang_hint: Optional[str] = None
    pipeline_version: Optional[str] = None  # 메타 기록용


@dataclass(frozen=True)
class ChunkInput:
    number: int               # 페이지/문단/슬롯 인덱스
    content: str
    meta: Optional[dict] = None


@dataclass
class IngestResult:
    """Ingest pipeline execution result"""

    group: Optional["DocumentGroup"]
    documents: List["Document"]
    total_files: int
    processed_files: int
    skipped_files: int
    failed_files: int = 0
    failed_details: Optional[dict] = field(default=None)  # {filename: error_message}
    deleted_files: int = 0  # Number of deleted files (removed from local but existed in DB)
    # For dry-run results
    files_to_process_indices: Optional[List[int]] = field(default=None)  # File indices that need processing
    unsupported_file_indices: Optional[List[int]] = field(default=None)  # Unsupported file indices
    files_to_delete: Optional[List[str]] = field(default=None)  # File names to be deleted (dry-run)
