"""Ingest Pipeline - LangGraph 기반

Graph: sync_documents → process_documents → END
"""
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from maru_lang.pipelines.ingest.state import IngestState
from maru_lang.pipelines.ingest.nodes import sync_documents, process_documents
from maru_lang.configs import get_config_manager
from maru_lang.schemas.ingest import FileInfo
from maru_lang.models.ingest import IngestResult


def create_ingest_graph(checkpointer=None):
    """Ingest StateGraph 생성 및 컴파일"""
    graph = StateGraph(IngestState)

    graph.add_node("sync_documents", sync_documents)
    graph.add_node("process_documents", process_documents)

    graph.set_entry_point("sync_documents")
    graph.add_edge("sync_documents", "process_documents")
    graph.add_edge("process_documents", END)

    return graph.compile(checkpointer=checkpointer)


async def run_ingest(
    files: list[FileInfo],
    team_id: int,
    re_embed: bool = False,
    vdb_config=None,
) -> IngestResult:
    """Ingest 파이프라인 실행"""
    config_manager = get_config_manager()
    embedder_config = config_manager.get_embedder_config()
    if not embedder_config or not embedder_config.default_model:
        raise ValueError("No embedding model configured in embedder_config.yaml")

    graph = create_ingest_graph()

    result = await graph.ainvoke({
        "files": files,
        "team_id": team_id,
        "re_embed": re_embed,
        "vdb_config": vdb_config,
        "all_documents": [],
        "documents_to_process": [],
        "processed_count": 0,
        "failed_documents": {},
        "total_chunks": 0,
        "messages": [],
        "embedder_model": embedder_config.default_model,
    })

    return IngestResult(
        group=None,
        documents=result["all_documents"],
        total_files=len(files),
        processed_files=result["processed_count"],
        skipped_files=len(result["all_documents"]) - len(result["documents_to_process"]),
        failed_files=len(result["failed_documents"]),
        failed_details=result["failed_documents"] or None,
        deleted_files=0,
    )


async def stream_ingest(
    files: list[FileInfo],
    team_id: int,
    re_embed: bool = False,
    vdb_config=None,
):
    """Ingest 파이프라인 스트리밍 실행

    Yields:
        (node_name, messages) 튜플
    """
    config_manager = get_config_manager()
    embedder_config = config_manager.get_embedder_config()
    if not embedder_config or not embedder_config.default_model:
        raise ValueError("No embedding model configured in embedder_config.yaml")

    graph = create_ingest_graph()

    initial_state = {
        "files": files,
        "team_id": team_id,
        "re_embed": re_embed,
        "vdb_config": vdb_config,
        "all_documents": [],
        "documents_to_process": [],
        "processed_count": 0,
        "failed_documents": {},
        "total_chunks": 0,
        "messages": [],
        "embedder_model": embedder_config.default_model,
    }

    async for event in graph.astream(initial_state, stream_mode="updates"):
        for node_name, state_update in event.items():
            messages = state_update.get("messages", [])
            if messages:
                yield node_name, messages
