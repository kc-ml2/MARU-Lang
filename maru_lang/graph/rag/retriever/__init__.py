"""Retriever - pluggable implementation selection.

추가 retriever(예: BM25/하이브리드)는 이 폴더에 모듈을 더하고, `build_retriever`의
선택 로직과 여기 export에 반영한다.
"""
from maru_lang.graph.rag.retriever.vector import VectorRetriever

__all__ = ["VectorRetriever", "build_retriever"]


def build_retriever(cfg):
    """config로부터 retriever를 생성한다 (현재는 VectorRetriever 단일)."""
    return VectorRetriever(
        top_k=cfg.retriever_top_k,
        search_method=cfg.retriever_search_method,
        embedding_model=cfg.embedding_model,
        embedding_device=cfg.embedding_device,
    )
