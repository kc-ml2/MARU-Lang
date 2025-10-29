"""
Configuration models for the LLM Chatbot application

Note: Most config models have been moved to pluggable.models
This module now only contains Group configuration which is not pluggable
"""
from .group import GroupConfig, GroupsConfig

# Import pluggable models for backward compatibility
from maru_lang.pluggable.models import (
    LLMConfig,
    AgentConfig,
    LoaderConfig,
    ExtensionMapping,
    ChunkerConfig,
    EmbedderConfig,
    ModelInfo,
    RerankerConfig,
)

__all__ = [
    "LLMConfig",
    "GroupConfig",
    "GroupsConfig",
    "AgentConfig",
    "LoaderConfig",
    "ExtensionMapping",
    "ChunkerConfig",
    "EmbedderConfig",
    "ModelInfo",
    "RerankerConfig",
]