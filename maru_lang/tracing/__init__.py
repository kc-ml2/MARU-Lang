"""
Unified tracing utilities.

This module provides Langfuse-based observability helpers that fail safely
when Langfuse is not installed or configured.

Example usage::

    from maru_lang.tracing import observe, safe_observe, get_tracing_status

    @observe(name="my_function")
    def my_function():
        pass

    @safe_observe(name="another_function")
    def another_function():
        pass
"""

# Langfuse core helpers
from .langfuse import (
    LangfuseWrapper,
    DummyContext,
    get_langfuse_wrapper,
    observe,
    flush,
    langfuse_wrapper
)

# Tracing utilities
from .base import (
    safe_observe,
    safe_span_update,
    get_tracing_status
)

__all__ = [
    # Langfuse helpers
    "LangfuseWrapper",
    "DummyContext", 
    "get_langfuse_wrapper",
    "observe",
    "flush",
    "langfuse_wrapper",

    # Tracing utilities
    "safe_observe",
    "safe_span_update", 
    "get_tracing_status"
]