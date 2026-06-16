"""Text splitter - pluggable implementation selection."""
from maru_lang.graph.ingest.splitter.langchain import create_splitter, split_documents

__all__ = ["create_splitter", "split_documents"]
