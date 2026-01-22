"""
Ingest Pipeline
"""
from maru_lang.pipelines.ingest.pipeline import IngestPipeline
from maru_lang.models.ingest import IngestResult

__all__ = [
    "IngestPipeline",
    "IngestResult",
]
