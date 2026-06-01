"""Merged RAG graph state.

Single state for the unified graph: the ReAct agent (chat) + the retrieval
pipeline (intent → keywords → retrieve → evaluate → rerank → format) + feedback.
"""
from typing import Annotated, Optional, TypedDict

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class RagState(TypedDict, total=False):
    # ---- conversation / agent ----
    messages: Annotated[list[BaseMessage], add_messages]  # conversation history
    team_ids: list[int]                                   # access control
    team_names: list[str]
    retrieved_documents: list[dict]                       # surfaced to API/persistence
    function: Optional[str]                               # e.g. "feedback" mode
    feedback_score: Optional[int]                         # user rating (1-5)
    feedback_reason: Optional[str]                        # reason for a low score

    # ---- retrieval pipeline (per-search working fields) ----
    query: str                                            # search query (from tool_call arg)
    rewritten_query: str                                  # intent-rewritten query
    keywords: list[str]                                   # extracted search keywords
    documents: list[Document]                             # retrieved documents
    result: str                                           # formatted output string
    retry_count: int                                      # retry count (max 2)
    evaluation: str                                       # "pass", "fail", or "max_retry"
    excluded_doc_ids: list[str]                           # IDs to exclude on retry (explicit concat)
    rag_log: list[str]                                    # progress log (diagnostic)

    # ---- search plumbing ----
    tool_call_id: Optional[str]                           # id of the knowledge_search call in flight
