"""Ingest graph state schema."""
from typing import Annotated, Optional, TypedDict
import operator

from maru_lang.schemas.ingest import FileInfo


class IngestState(TypedDict):
    """Shared state for the single-file ingest pipeline.

    Attributes:
        file: Single file to process.
        team_id: Team ID for document ownership.
        re_embed: Whether to force re-embedding.
        embedder_model: Embedding model name.
        document: Synced document info (set by sync node).
        needs_processing: Whether the file needs processing.
        total_chunks: Number of chunks created.
        error: Error message if processing failed.
        messages: Progress messages (accumulated via operator.add).
    """
    # Input
    file: FileInfo
    team_id: int
    re_embed: bool
    embedder_model: str

    # Progress
    document: Optional[dict]
    needs_processing: bool
    total_chunks: int
    error: Optional[str]
    messages: Annotated[list[str], operator.add]
