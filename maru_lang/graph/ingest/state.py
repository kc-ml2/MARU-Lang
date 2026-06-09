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
        document: Synced document info (set by sync node).
        needs_processing: Whether the file needs processing.
        parsed_docs: Parsed content as [{content, metadata}] (set by parse node).
        parser: Parser used for this document (set by parse node).
        total_chunks: Number of chunks created.
        error: Error message if processing failed.
        messages: Progress messages (accumulated via operator.add).
    """
    # Input
    file: FileInfo
    team_id: int
    re_embed: bool

    # Progress
    document: Optional[dict]
    needs_processing: bool
    parsed_docs: Optional[list[dict]]
    parser: Optional[str]
    total_chunks: int
    error: Optional[str]
    messages: Annotated[list[str], operator.add]


def build_ingest_input(
    team_id: int,
    *,
    file: Optional[FileInfo] = None,
    re_embed: bool = False,
    document: Optional[dict] = None,
    needs_processing: bool = False,
) -> IngestState:
    """Build the graph's initial state — the single source of its key set.

    Two entry shapes feed the same graph:
        - From a filesystem file (CLI sync): pass `file`; sync_document creates
          the Document record and decides needs_processing.
        - From an already-synced document (API upload / ARQ worker): pass
          `document` (+ needs_processing=True); sync_document skips.

    The embedding model/device are not in the state — they're injected into the
    process_document node at graph construction (see create_ingest_graph).
    """
    return {
        "file": file,
        "team_id": team_id,
        "re_embed": re_embed,
        "document": document,
        "needs_processing": needs_processing,
        "parsed_docs": None,
        "parser": None,
        "total_chunks": 0,
        "error": None,
        "messages": [],
    }
