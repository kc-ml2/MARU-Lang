"""
Configuration type enums
"""
from enum import Enum


class ConfigType(Enum):
    """Configuration types"""
    LLMS = "llms"
    RAGS = "rags"  # RAG 설정 (retriever + groups)
    AGENTS = "agents"
    LOADERS = "loaders"
    CHUNKERS = "chunkers"
    EMBEDDERS = "embedders"
    RERANKERS = "rerankers"