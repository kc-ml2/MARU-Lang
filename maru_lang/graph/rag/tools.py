"""Schema-only tool for the ReAct agent.

The agent binds this tool so the LLM can decide to search and emit a structured
tool_call. The body is never executed — the graph itself runs the RAG pipeline
(see nodes/search.py). It exists purely to provide the binding schema.
"""
from langchain_core.tools import tool


@tool
async def knowledge_search(query: str) -> str:
    """Search team documents for relevant information.
    Use this tool to find internal documents when answering user questions.

    Args:
        query: Search query or keywords.
    """
    # Never executed: the graph routes tool_calls into the RAG nodes.
    return ""
