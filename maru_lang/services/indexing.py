"""Orchestration for source extraction, chunking, and index synchronization."""
from __future__ import annotations

from collections.abc import AsyncIterator

from maru_lang.enums import PipelineStage
from maru_lang.pipeline import PipelineConfig
from maru_lang.ports.indexing import (
    ChunkedDocument,
    DocumentChunker,
    DocumentSource,
    IndexingReport,
    IndexSink,
)


class IndexingService:
    """Compose MARU's fixed indexing stages from registered implementations."""

    def __init__(
        self,
        source: DocumentSource,
        chunker: DocumentChunker,
        sink: IndexSink,
    ) -> None:
        self._source = source
        self._chunker = chunker
        self._sink = sink

    async def execute(
        self,
        storage_id: str,
        config: PipelineConfig,
        from_stage: PipelineStage,
    ) -> IndexingReport:
        """Execute the configured pipeline.

        This compositional executor currently supports full runs only. Concrete
        stage-aware executors must replace it before selective reruns are enabled.
        """
        if from_stage != PipelineStage.SCAN:
            raise NotImplementedError("Selective pipeline reruns are not configured")
        if not storage_id:
            raise ValueError("Storage ID must not be empty")

        async def chunked_documents() -> AsyncIterator[ChunkedDocument]:
            async for document in self._source.iter_documents(storage_id):
                if document.storage_id != storage_id:
                    raise ValueError("Document source returned a different storage ID")
                chunks = tuple(await self._chunker.split(document))
                if any(not chunk.content.strip() for chunk in chunks):
                    raise ValueError("Chunk content must not be empty")
                yield ChunkedDocument(source=document, chunks=chunks)

        return await self._sink.synchronize(storage_id, chunked_documents())
