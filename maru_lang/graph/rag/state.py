"""Merged RAG graph state.

Single state for the unified graph: the ReAct agent (chat) + the retrieval
pipeline (intent → keywords → retrieve → evaluate → rerank → format) + feedback.
"""
from typing import Annotated, Optional, TypedDict

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph.message import add_messages


class RagState(TypedDict, total=False):
    # ---- conversation / agent ----
    messages: Annotated[list[BaseMessage], add_messages]  # conversation history
    team_ids: list[int]                                   # access control
    team_names: list[str]
    session_id: Optional[str]                             # chat session (for memory lookup/persist)
    user_id: Optional[int]                                # owner (for persist)
    question: Optional[str]                               # this turn's user question
    answer: Optional[str]                                 # this turn's generated answer
    memory_context: Optional[str]                         # assembled prior-conversation context
    retrieved_documents: list[dict]                       # surfaced to API/persistence
    function: Optional[str]                               # e.g. "feedback" mode
    feedback_score: Optional[int]                         # user rating (1-5)
    feedback_reason: Optional[str]                        # reason for a low score
    llm_name: Optional[str]                               # LLM actually running this turn (for audit/persist)

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

    # ---- routing ----
    route: Optional[str]                                  # "search" | "direct" (set by route node)


def build_input(
    message: str,
    team_ids: list[int],
    team_names: list[str],
    function: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[int] = None,
    llm_name: Optional[str] = None,
) -> RagState:
    """그래프 초기 입력 state를 만든다."""
    return {
        "messages": [HumanMessage(content=message)],
        "team_ids": team_ids,
        "team_names": team_names,
        "session_id": session_id,
        "user_id": user_id,
        "question": message,
        "function": function,
        "llm_name": llm_name,
    }
