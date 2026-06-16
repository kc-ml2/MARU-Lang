"""Document loader - pluggable implementation selection."""
from maru_lang.graph.ingest.loader.langchain import load_file, is_supported

__all__ = ["load_file", "is_supported"]
