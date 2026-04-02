"""Retriever - pluggable implementation selection."""
from maru_lang.graph.rag.retriever.vector import VectorRetriever
from maru_lang.graph.rag.retriever.compressed import CompressedRetriever

__all__ = ["VectorRetriever", "CompressedRetriever"]
