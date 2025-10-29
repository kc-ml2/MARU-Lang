import os
import functools
from maru_lang.core.settings import settings
from typing import Optional, Any, Callable, Dict


class LangfuseWrapper:
    """Provide Langfuse integration while failing gracefully when unavailable."""

    def __init__(self):
        self.langfuse = None
        self.observe_decorator = None
        self.is_available = False

        self._initialize_langfuse()

    def _initialize_langfuse(self):
        """Attempt to initialize Langfuse."""
        try:
            # Validate configuration values
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

            # Initialize Langfuse
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
        Optional wrapper for the Langfuse ``observe`` decorator.

        Args:
            name: Name of the function or method to observe.
            **kwargs: Additional arguments forwarded to ``observe``.

        Returns:
            The actual decorator function.
        """
        def decorator(func: Callable) -> Callable:
            if self.is_available and self.observe_decorator:
                # Apply the true Langfuse decorator when available
                return self.observe_decorator(name=name or func.__name__, **kwargs)(func)
            else:
                # Otherwise return the original function unchanged
                @functools.wraps(func)
                def wrapper(*args, **kwargs):
                    return func(*args, **kwargs)
                return wrapper

        return decorator

    def flush(self):
        """Flush Langfuse spans when available."""
        if self.is_available and self.langfuse:
            self.langfuse.flush()


class DummyContext:
    """Dummy context manager used when Langfuse is unavailable."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def update(self, **kwargs):
        pass

    def score(self, **kwargs):
        pass


# Convenience helpers
_langfuse_wrapper = None


def get_langfuse_wrapper() -> LangfuseWrapper:
    """Return the shared LangfuseWrapper instance."""
    global _langfuse_wrapper
    if _langfuse_wrapper is None:
        _langfuse_wrapper = LangfuseWrapper()
    return _langfuse_wrapper


def observe(name: Optional[str] = None, **kwargs) -> Callable:
    """
    Optional Langfuse observe decorator.

    Example::

        @observe(name="my_function")
        def my_function():
            ...
    """
    return get_langfuse_wrapper().observe(name=name, **kwargs)


def flush():
    """Flush Langfuse spans when the integration is available."""
    get_langfuse_wrapper().flush()


# Backward compatibility
langfuse_wrapper = get_langfuse_wrapper()