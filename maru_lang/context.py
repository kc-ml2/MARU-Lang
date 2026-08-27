"""Application-owned services shared by HTTP and MCP transports."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from maru_lang.dependencies.email import EmailService
from maru_lang.settings import Settings
from maru_lang.utils.security import TokenCodec


@dataclass(frozen=True, slots=True)
class AppContext:
    settings: Settings
    tokens: TokenCodec
    email: EmailService | None


def get_app_context(request: Request) -> AppContext:
    """Resolve the application context without process-global state."""
    return request.app.state.context
