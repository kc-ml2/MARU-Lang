"""Ingest Pipeline State - LangGraph 상태 스키마"""
from typing import Annotated, Optional, TypedDict
import operator

from maru_lang.models.vector_db import BaseVectorDBConfig
from maru_lang.schemas.ingest import FileInfo


class IngestState(TypedDict):
    """Ingest 파이프라인의 공유 상태"""
    # 입력
    files: list[FileInfo]
    team_id: int
    re_embed: bool
    vdb_config: Optional[BaseVectorDBConfig]
    embedder_model: str

    # 진행 중 업데이트
    all_documents: list[dict]
    documents_to_process: list[dict]
    processed_count: int
    failed_documents: dict
    total_chunks: int
    messages: Annotated[list[str], operator.add]
