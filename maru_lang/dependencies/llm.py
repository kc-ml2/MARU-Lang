from maru_lang.pluggable.llms import LLMServerClient, LLMServerManager


_llm_manager = None


async def get_llm_manager() -> LLMServerManager:
    """LLMServerManager 인스턴스를 반환합니다."""
    global _llm_manager
    if _llm_manager is None:
        _llm_manager = LLMServerManager()
    # 서버가 초기화되지 않았다면 초기화
    if not _llm_manager.all_servers:
        await _llm_manager.initialize_servers()

    return _llm_manager


async def get_llm() -> LLMServerClient | None:
    """활성화된 LLM 서버 중 하나를 반환합니다."""
    manager = await get_llm_manager()


    return await manager.get_active_server()
