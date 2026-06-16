"""Reranker - pluggable implementation selection."""
from maru_lang.graph.rag.reranker.cross_encoder import (
    CrossEncoderCompressor,
    clear_model_cache,
)
from maru_lang.graph.rag.reranker.llm import LLMReranker
from maru_lang.core.llm.client import create_chat_model

__all__ = ["CrossEncoderCompressor", "LLMReranker", "clear_model_cache", "build_compressor"]


def build_compressor(cfg):
    """config로부터 reranker(compressor)를 생성한다. reranking 비활성이면 None."""
    if not cfg.reranker_enabled:
        return None

    if cfg.reranker_type == "llm":
        llm_config = None
        for llm in cfg.llms:
            if cfg.reranker_llm and llm.name == cfg.reranker_llm:
                llm_config = llm
                break
        if llm_config is None and cfg.llms:
            llm_config = cfg.llms[0]
        if llm_config is None:
            raise RuntimeError("LLM reranker requires at least one LLM in config.")
        return LLMReranker(llm=create_chat_model(llm_config), top_k=cfg.reranker_top_k or 3)

    return CrossEncoderCompressor(
        model_name=cfg.reranker_model,
        top_k=cfg.reranker_top_k,
        device=cfg.reranker_device or cfg.embedding_device,
        min_score=cfg.reranker_min_score,
    )
