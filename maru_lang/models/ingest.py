from dataclasses import dataclass
from typing import Optional


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
