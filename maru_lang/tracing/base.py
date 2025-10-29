"""
Langfuse tracing utilities.
"""
from typing import Any, Dict, Optional
from .langfuse import get_langfuse_wrapper, observe


def safe_observe(name: Optional[str] = None, **kwargs):
    """
    A defensive version of ``@observe`` that becomes a no-op when Langfuse is
    unavailable.

    Example::

        @safe_observe(name="function_name", as_type="generation")
        def my_function():
            ...
    """
    def decorator(func):
        langfuse_wrapper = get_langfuse_wrapper()
        if not langfuse_wrapper.is_available:
            # Return the original function when Langfuse is disabled
            return func
        
        # Apply the actual observe decorator when Langfuse is enabled
        actual_name = name or func.__name__
        return observe(name=actual_name, **kwargs)(func)
    
    return decorator


def safe_span_update(span: Any, data: Dict[str, Any]) -> bool:
    """Update a span safely when Langfuse is configured."""
    langfuse_wrapper = get_langfuse_wrapper()
    if not span or not langfuse_wrapper.is_available:
        return False
        
    try:
        # Sanitize any None values before updating
        safe_data = _sanitize_data(data)
        span.update_trace(**safe_data)
        return True
    except Exception as e:
        print(f"⚠️  Span update failed: {e}")
        return False


def _sanitize_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize trace data by replacing ``None`` values."""
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
    """Normalize each item inside nested data structures."""
    if item is None:
        return "null"
    elif isinstance(item, dict):
        return _sanitize_data(item)
    else:
        return item


def get_tracing_status() -> Dict[str, Any]:
    """Return the current tracing status."""
    langfuse_wrapper = get_langfuse_wrapper()
    return {
        "enabled": langfuse_wrapper.is_available,
        "status": "enabled" if langfuse_wrapper.is_available else "disabled"
    }