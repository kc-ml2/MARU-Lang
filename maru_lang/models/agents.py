"""
Agent-related data models
"""
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class AgentResult:
    """Result from individual agent execution"""
    status: str
    payload: Optional[Any] = None
    error: Optional[str] = None
