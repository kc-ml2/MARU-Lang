"""LLM dependency injection"""
from typing import Optional

from langchain_core.language_models import BaseChatModel

from maru_lang.pluggable.llms import LLMClient, LLMManager


_llm_manager: LLMManager | None = None


def get_llm_manager() -> LLMManager:
    """Return the LLMManager instance."""
    global _llm_manager
    if _llm_manager is None:
        _llm_manager = LLMManager()
        _llm_manager.initialize()
    return _llm_manager


def get_llm() -> Optional[LLMClient]:
    """Return the first available LLMClient."""
    manager = get_llm_manager()
    return manager.get_client()


def get_model(name: Optional[str] = None) -> Optional[BaseChatModel]:
    """Return a LangChain ChatModel directly."""
    manager = get_llm_manager()
    return manager.get_model(name)


def get_model_with_fallbacks(primary_name: Optional[str] = None) -> Optional[BaseChatModel]:
    """Return a ChatModel with fallback chain."""
    manager = get_llm_manager()
    return manager.get_model_with_fallbacks(primary_name)
