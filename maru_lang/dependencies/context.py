"""FastAPI dependency for the application-owned context."""
from fastapi import Request

from maru_lang.context import AppContext


def get_app_context(request: Request) -> AppContext:
    return request.app.state.context
