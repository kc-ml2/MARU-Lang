"""LLM management - client, manager, and convenience accessors."""
import threading
from typing import Optional

from langchain_core.language_models import BaseChatModel

from .client import LLMClient
from .server_manager import LLMManager

__all__ = ["LLMClient", "LLMManager", "get_model_with_fallbacks"]

_llm_manager: LLMManager | None = None
_llm_manager_lock = threading.Lock()


def _get_llm_manager() -> LLMManager:
    global _llm_manager
    if _llm_manager is None:
        with _llm_manager_lock:
            if _llm_manager is None:
                manager = LLMManager()
                manager.initialize()
                _llm_manager = manager
    return _llm_manager


def get_model_with_fallbacks(primary_name: Optional[str] = None) -> Optional[BaseChatModel]:
    """Return a ChatModel with fallback chain."""
    return _get_llm_manager().get_model_with_fallbacks(primary_name)
