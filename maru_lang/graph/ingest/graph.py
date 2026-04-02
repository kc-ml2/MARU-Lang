"""Ingest graph definition and execution.

Graph: sync_document -> process_document -> END

Config is read internally. Callers just call run_ingest(file, team_id).
"""
from typing import AsyncIterator

from langgraph.graph import StateGraph, END

from maru_lang.configs import get_config
from maru_lang.graph.ingest.state import IngestState
from maru_lang.graph.ingest.nodes import sync_document, process_document
from maru_lang.schemas.ingest import FileInfo


def create_ingest_graph(checkpointer=None):
    """Create and compile the ingest StateGraph."""
    graph = StateGraph(IngestState)

    graph.add_node("sync_document", sync_document)
    graph.add_node("process_document", process_document)

    graph.set_entry_point("sync_document")
    graph.add_edge("sync_document", "process_document")
    graph.add_edge("process_document", END)

    return graph.compile(checkpointer=checkpointer)


async def run_ingest(
    file: FileInfo,
    team_id: int,
    re_embed: bool = False,
) -> dict:
    """Run the ingest pipeline for a single file.

    Reads embedding config internally.

    Args:
        file: File to ingest.
        team_id: Team ID for document ownership.
        re_embed: Force re-embedding even if unchanged.

    Returns:
        Final state dict with document, total_chunks, error, messages.
    """
    cfg = get_config()

    graph = create_ingest_graph()

    return await graph.ainvoke({
        "file": file,
        "team_id": team_id,
        "re_embed": re_embed,
        "embedder_model": cfg.embedding_model,
        "document": None,
        "needs_processing": False,
        "total_chunks": 0,
        "error": None,
        "messages": [],
    })


async def stream_ingest(
    file: FileInfo,
    team_id: int,
    re_embed: bool = False,
) -> AsyncIterator[tuple[str, list[str]]]:
    """Stream the ingest pipeline for a single file.

    Reads embedding config internally.

    Args:
        file: File to ingest.
        team_id: Team ID for document ownership.
        re_embed: Force re-embedding even if unchanged.

    Yields:
        (node_name, messages) tuples.
    """
    cfg = get_config()

    graph = create_ingest_graph()

    initial_state = {
        "file": file,
        "team_id": team_id,
        "re_embed": re_embed,
        "embedder_model": cfg.embedding_model,
        "document": None,
        "needs_processing": False,
        "total_chunks": 0,
        "error": None,
        "messages": [],
    }

    async for event in graph.astream(initial_state, stream_mode="updates"):
        for node_name, state_update in event.items():
            messages = state_update.get("messages", [])
            if messages:
                yield node_name, messages
