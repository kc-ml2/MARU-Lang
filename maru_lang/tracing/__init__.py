"""
통합 트레이싱 모듈

이 모듈은 Langfuse 기반의 관찰가능성(observability) 기능을 제공합니다.
Langfuse가 설치되지 않았거나 설정되지 않은 경우에도 안전하게 동작합니다.

사용법:
    from maru_lang.tracing import observe, safe_observe, get_tracing_status
    
    @observe(name="my_function")
    def my_function():
        pass
        
    @safe_observe(name="another_function")
    def another_function():
        pass
"""

# Langfuse 관련 기본 기능들
from .langfuse import (
    LangfuseWrapper,
    DummyContext,
    get_langfuse_wrapper,
    observe,
    flush,
    langfuse_wrapper
)

# 트레이싱 유틸리티들
from .base import (
    safe_observe,
    safe_span_update,
    get_tracing_status
)

__all__ = [
    # Langfuse 기본 기능
    "LangfuseWrapper",
    "DummyContext", 
    "get_langfuse_wrapper",
    "observe",
    "flush",
    "langfuse_wrapper",
    
    # 트레이싱 유틸리티
    "safe_observe",
    "safe_span_update", 
    "get_tracing_status"
]