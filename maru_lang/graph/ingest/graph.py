"""Ingest graph definition and execution.

Graph: sync_document -> parse_document -> process_document -> END

Config is read internally. Callers just call run_ingest(file, team_id).
"""
from typing import AsyncIterator

from langgraph.graph import StateGraph, END

from maru_lang.configs import get_config
from maru_lang.core.vector_db import get_vector_db
from maru_lang.graph.ingest.embedder import get_embeddings
from maru_lang.graph.ingest.state import IngestState, build_ingest_input
from maru_lang.graph.ingest.nodes import (
    sync_document,
    parse_document,
    make_process_document_node,
)
from maru_lang.schemas.ingest import FileInfo


def create_ingest_graph(*, vdb, embeddings, checkpointer=None):
    """Create and compile the ingest StateGraph.

    Args:
        vdb: Vector DB client, injected into process_document.
        embeddings: Embeddings client, injected into process_document.
        checkpointer: Optional LangGraph checkpointer.
    """
    graph = StateGraph(IngestState)

    graph.add_node("sync_document", sync_document)
    graph.add_node("parse_document", parse_document)
    graph.add_node("process_document", make_process_document_node(vdb, embeddings))

    graph.set_entry_point("sync_document")
    graph.add_edge("sync_document", "parse_document")
    graph.add_edge("parse_document", "process_document")
    graph.add_edge("process_document", END)

    return graph.compile(checkpointer=checkpointer)


_ingest_graph = None


def get_ingest_graph():
    """Return the shared, compiled ingest graph (built once, stateless).

    Builds the vector DB + embeddings once and injects them, then reuses the one
    compiled instance across files (the graph carries no per-call state and the
    checkpointer is unused), instead of recompiling/reloading per call.
    """
    global _ingest_graph
    if _ingest_graph is None:
        cfg = get_config()
        _ingest_graph = create_ingest_graph(
            vdb=get_vector_db(),
            embeddings=get_embeddings(
                cfg.embedding_model, cfg.resolve_ingest_embedding_device()
            ),
        )
    return _ingest_graph


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
    state = build_ingest_input(team_id, file=file, re_embed=re_embed)
    return await get_ingest_graph().ainvoke(state)


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
    initial_state = build_ingest_input(team_id, file=file, re_embed=re_embed)

    async for event in get_ingest_graph().astream(initial_state, stream_mode="updates"):
        for node_name, state_update in event.items():
            messages = state_update.get("messages", [])
            if messages:
                yield node_name, messages
