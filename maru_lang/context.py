"""Application-owned services shared by HTTP and MCP transports."""
from __future__ import annotations

from dataclasses import dataclass

from maru_lang.ports.email import EmailService
from maru_lang.settings import Settings
from maru_lang.utils.security import TokenCodec


@dataclass(frozen=True, slots=True)
class AppContext:
    settings: Settings
    tokens: TokenCodec
    email: EmailService | None
