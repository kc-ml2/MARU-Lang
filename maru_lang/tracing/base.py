"""
Langfuse 트레이싱 유틸리티
"""
from typing import Any, Dict, Optional
from .langfuse import get_langfuse_wrapper, observe


def safe_observe(name: Optional[str] = None, **kwargs):
    """
    안전한 observe 데코레이터 - 기존 @observe 스타일 유지
    
    사용법:
        @safe_observe(name="function_name", as_type="generation")
        def my_function():
            pass
    """
    def decorator(func):
        langfuse_wrapper = get_langfuse_wrapper()
        if not langfuse_wrapper.is_available:
            # Langfuse가 비활성화되어 있으면 원본 함수 반환
            return func
        
        # Langfuse가 활성화되어 있으면 실제 observe 데코레이터 적용
        actual_name = name or func.__name__
        return observe(name=actual_name, **kwargs)(func)
    
    return decorator


def safe_span_update(span: Any, data: Dict[str, Any]) -> bool:
    """안전한 span 업데이트"""
    langfuse_wrapper = get_langfuse_wrapper()
    if not span or not langfuse_wrapper.is_available:
        return False
        
    try:
        # None 값들을 안전한 값으로 변환
        safe_data = _sanitize_data(data)
        span.update_trace(**safe_data)
        return True
    except Exception as e:
        print(f"⚠️  Span update failed: {e}")
        return False


def _sanitize_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """데이터 정화 - None 값들을 안전한 값으로 변환"""
    safe_data = {}
    
    for key, value in data.items():
        if value is None:
            if key == "answer":
                safe_data[key] = "No response generated"
            elif key in ["user_id", "session_id"]:
                safe_data[key] = "unknown"
            elif isinstance(value, list):
                safe_data[key] = []
            else:
                safe_data[key] = str(value) if value is not None else "null"
        elif isinstance(value, list):
            safe_data[key] = [_sanitize_item(item) for item in value]
        else:
            safe_data[key] = value
            
    return safe_data


def _sanitize_item(item: Any) -> Any:
    """개별 아이템 정화"""
    if item is None:
        return "null"
    elif isinstance(item, dict):
        return _sanitize_data(item)
    else:
        return item


def get_tracing_status() -> Dict[str, Any]:
    """트레이싱 상태 반환"""
    langfuse_wrapper = get_langfuse_wrapper()
    return {
        "enabled": langfuse_wrapper.is_available,
        "status": "enabled" if langfuse_wrapper.is_available else "disabled"
    }