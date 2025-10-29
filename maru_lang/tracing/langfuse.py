import os
import functools
from maru_lang.core.settings import settings
from typing import Optional, Any, Callable, Dict


class LangfuseWrapper:
    """
    Langfuse가 없으면 데코레이터가 아무 동작도 하지 않음
    """

    def __init__(self):
        self.langfuse = None
        self.observe_decorator = None
        self.is_available = False

        self._initialize_langfuse()

    def _initialize_langfuse(self):
        """Langfuse 초기화 시도"""
        try:
            # 설정값 검증
            if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
                print("⚠️  Langfuse keys not configured. Tracing disabled.")
                return
                
            from langfuse import get_client, observe

            os.environ.update({
                "LANGFUSE_PUBLIC_KEY": settings.LANGFUSE_PUBLIC_KEY,
                "LANGFUSE_SECRET_KEY": settings.LANGFUSE_SECRET_KEY,
                "LANGFUSE_HOST": settings.LANGFUSE_HOST,
                "LANGFUSE_DEBUG": "False"
            })

            # Langfuse 초기화
            self.langfuse = get_client()
            self.observe_decorator = observe
            self.is_available = True
            
            print("✅ Langfuse initialized successfully")

        except ImportError:
            print("⚠️  Langfuse not installed. Tracing disabled.")
        except Exception as e:
            print(f"⚠️  Langfuse initialization failed: {e}. Tracing disabled.")
            self.is_available = False

    def observe(self, name: Optional[str] = None, **kwargs) -> Callable:
        """
        Langfuse observe 데코레이터의 옵셔널 래퍼

        Args:
            name: 관찰할 함수/메서드의 이름
            **kwargs: observe 데코레이터에 전달할 추가 인자들

        Returns:
            실제 데코레이터 함수
        """
        def decorator(func: Callable) -> Callable:
            if self.is_available and self.observe_decorator:
                # Langfuse가 사용 가능하면 실제 observe 데코레이터 적용
                return self.observe_decorator(name=name or func.__name__, **kwargs)(func)
            else:
                # Langfuse가 없으면 원본 함수 그대로 반환
                @functools.wraps(func)
                def wrapper(*args, **kwargs):
                    return func(*args, **kwargs)
                return wrapper

        return decorator

    def flush(self):
        """Langfuse flush (있을 경우에만)"""
        if self.is_available and self.langfuse:
            self.langfuse.flush()


class DummyContext:
    """Langfuse가 없을 때 사용하는 더미 컨텍스트 매니저"""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def update(self, **kwargs):
        pass

    def score(self, **kwargs):
        pass


# 편의를 위한 함수들
_langfuse_wrapper = None


def get_langfuse_wrapper() -> LangfuseWrapper:
    """LangfuseWrapper 인스턴스를 반환"""
    global _langfuse_wrapper
    if _langfuse_wrapper is None:
        _langfuse_wrapper = LangfuseWrapper()
    return _langfuse_wrapper


def observe(name: Optional[str] = None, **kwargs) -> Callable:
    """
    옵셔널 Langfuse observe 데코레이터

    사용법:
        @observe(name="my_function")
        def my_function():
            pass
    """
    return get_langfuse_wrapper().observe(name=name, **kwargs)


def flush():
    """Langfuse flush (사용 가능할 때만)"""
    get_langfuse_wrapper().flush()


# Backward compatibility
langfuse_wrapper = get_langfuse_wrapper()