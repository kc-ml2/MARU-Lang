"""MaruLang - Advanced AI Agent Framework with RAG and multi-agent system"""

__version__ = "0.0.0"

from maru_lang.app import MaruLangApp, default_app

# FastAPI app instance
app = default_app.get_fastapi_app()

__all__ = [
    "MaruLangApp",
    "default_app",
    "app",
    "__version__",
]