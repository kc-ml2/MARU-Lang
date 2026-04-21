"""RAG graph state."""
from typing import Annotated, Optional, TypedDict
import operator

from langchain_core.documents import Document


class RagState(TypedDict):
    query: str                                          # Original query
    rewritten_query: str                                # Intent-rewritten query
    keywords: list[str]                                 # Extracted search keywords
    documents: list[Document]                           # Retrieved documents
    result: str                                         # Formatted output string
    team_ids: list[int]                                 # Access control
    retry_count: int                                    # Retry count (max 2)
    evaluation: str                                     # "pass", "fail", or "max_retry"
    excluded_doc_ids: Annotated[list[str], operator.add]  # IDs to exclude on retry
    messages: Annotated[list[str], operator.add]        # Progress log
