"""
Unified configuration management system

Note: Most config loaders have been moved to pluggable.configs
This module provides backward compatibility imports and manages non-pluggable configs
"""
from .base import DefaultConfigLoader
from .manager import ConfigManager, get_config_manager

# Import pluggable configs for backward compatibility
from maru_lang.pluggable.configs import (
    LLMConfigLoader,
    AgentConfigLoader,
    LoaderConfigLoader,
    ChunkerConfigLoader,
    EmbedderConfigLoader,
    RerankerConfigLoader,
    RagConfigLoader,
)

# Import models for convenience
from maru_lang.models.configs import (
    LLMConfig,
    GroupConfig,
    GroupsConfig,
    AgentConfig,
    LoaderConfig,
    ChunkerConfig,
    EmbedderConfig,
    RerankerConfig,
)

# Import RAG models
from maru_lang.pluggable.models import (
    RagConfig,
    RetrieverConfig,
    GroupRagConfig,
)

__all__ = [
    # Base
    'DefaultConfigLoader',

    # RAG (replaces Group)
    'RagConfig',
    'RetrieverConfig',
    'GroupRagConfig',
    'RagConfigLoader',

    # Backward compatibility - Group (deprecated, use RAG instead)
    'GroupConfig',
    'GroupsConfig',

    # Pluggable configs (re-exported for convenience)
    'LLMConfig',
    'LLMConfigLoader',
    'AgentConfig',
    'AgentConfigLoader',
    'LoaderConfig',
    'LoaderConfigLoader',
    'ChunkerConfig',
    'ChunkerConfigLoader',
    'EmbedderConfig',
    'EmbedderConfigLoader',
    'RerankerConfig',
    'RerankerConfigLoader',

    # Config Manager
    'ConfigManager',
    'get_config_manager',
]
