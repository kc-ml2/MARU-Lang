"""LLM management - client, manager, and convenience accessors."""
from typing import Optional

from langchain_core.language_models import BaseChatModel

from .client import LLMClient
from .server_manager import LLMManager

__all__ = ["LLMClient", "LLMManager", "get_model_with_fallbacks"]

_llm_manager: LLMManager | None = None


def _get_llm_manager() -> LLMManager:
    global _llm_manager
    if _llm_manager is None:
        _llm_manager = LLMManager()
        _llm_manager.initialize()
    return _llm_manager


def get_model_with_fallbacks(primary_name: Optional[str] = None) -> Optional[BaseChatModel]:
    """Return a ChatModel with fallback chain."""
    return _get_llm_manager().get_model_with_fallbacks(primary_name)
