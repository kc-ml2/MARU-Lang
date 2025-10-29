"""
Retriever for handling search operations.

Note: Retriever has been moved to pluggable.retrievers
This module provides backward compatibility imports
"""

from maru_lang.pluggable.retrievers import (
    Retriever,
    get_retriever,
    SearchMethod,
)

__all__ = [
    "Retriever",
    "get_retriever",
    "SearchMethod",
]
