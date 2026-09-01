"""Contracts for turning source documents into independently indexed chunks."""
from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from maru_lang.enums import PipelineStage
from maru_lang.pipeline import PipelineConfig


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """Storage-relative content emitted by a filesystem or external source."""

    storage_id: str
    relative_path: str
    content: str
    content_hash: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    """A chunk before persistence and embedding-specific identifiers are added."""

    content: str
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChunkedDocument:
    """One source document and the ordered chunks derived from it."""

    source: SourceDocument
    chunks: tuple[ChunkDraft, ...]


@dataclass(frozen=True, slots=True)
class IndexingReport:
    """Backend-neutral summary of a completed storage synchronization."""

    storage_id: str
    documents_seen: int
    chunks_written: int
    documents_deleted: int = 0


class PipelineExecutor(Protocol):
    """Execute MARU's fixed pipeline while honoring its stage and config."""

    async def execute(
        self,
        storage_id: str,
        config: PipelineConfig,
        from_stage: PipelineStage,
    ) -> IndexingReport: ...


class DocumentSource(Protocol):
    """Discover and extract documents from a storage or external system."""

    def iter_documents(self, storage_id: str) -> AsyncIterator[SourceDocument]: ...


class DocumentChunker(Protocol):
    """Split extracted content without knowing how chunks will be indexed."""

    async def split(self, document: SourceDocument) -> Sequence[ChunkDraft]: ...


class IndexSink(Protocol):
    """Synchronize chunked documents with a local or external index.

    Implementations own embedding, vector persistence, stale-document deletion,
    and transaction semantics. They must treat ``relative_path`` as a document's
    identity within a storage.
    """

    async def synchronize(
        self,
        storage_id: str,
        documents: AsyncIterator[ChunkedDocument],
    ) -> IndexingReport: ...
