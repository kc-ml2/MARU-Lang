"""Embedder - pluggable implementation selection."""
from maru_lang.graph.ingest.embedder.huggingface import get_embeddings, clear_cache

__all__ = ["get_embeddings", "clear_cache"]
