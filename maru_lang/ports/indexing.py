"""Execution contract for MARU's fixed PostgreSQL indexing pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from maru_lang.enums import PipelineStage
from maru_lang.pipeline import PipelineConfig


@dataclass(frozen=True, slots=True)
class IndexingReport:
    storage_id: str
    documents_seen: int
    chunks_written: int
    documents_deleted: int = 0


class PipelineExecutor(Protocol):
    """Run the fixed pipeline from one of its supported stages."""

    async def execute(
        self,
        storage_id: str,
        config: PipelineConfig,
        from_stage: PipelineStage,
    ) -> IndexingReport: ...
