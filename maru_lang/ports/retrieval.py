"""Backend-neutral contracts for team-authorized document retrieval."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    """A query whose storage scope has already been authorized by MARU."""

    text: str
    storage_ids: tuple[str, ...]
    limit: int = 10
    filters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("Retrieval query must not be empty")
        if self.limit < 1:
            raise ValueError("Retrieval limit must be at least 1")


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """One ranked result returned by a local or external retrieval backend."""

    storage_id: str
    document_id: str
    chunk_id: str
    relative_path: str
    content: str
    score: float
    metadata: Mapping[str, object] = field(default_factory=dict)


class RetrievalBackend(Protocol):
    """Search only the storage IDs supplied in an authorized query."""

    async def search(self, query: RetrievalQuery) -> Sequence[RetrievedChunk]: ...
