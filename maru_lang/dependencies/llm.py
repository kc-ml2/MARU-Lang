from maru_lang.pluggable.llms import LLMClient, LLMManager


_llm_manager: LLMManager | None = None


def get_llm_manager() -> LLMManager:
    """Return the LLMManager instance."""
    global _llm_manager
    if _llm_manager is None:
        _llm_manager = LLMManager()
        _llm_manager.initialize()
    return _llm_manager


def get_llm() -> LLMClient | None:
    """Return an LLM client."""
    manager = get_llm_manager()
    return manager.get_client()
