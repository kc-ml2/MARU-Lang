"""
Agent-related enums
"""
from enum import Enum


class LLMFallbackStrategy(Enum):
    """LLM fallback strategies when specified LLM server is not available"""
    ANY_AVAILABLE = "any_available"  # Use any available LLM server
    ERROR = "error"                  # Raise error and stop execution