"""Memory tools - long-term memory read/write.

Uses an in-memory dict for development.
Will be replaced with VectorDB memory collection later.
"""
from datetime import datetime
from langchain_core.tools import tool

_memory_store: list[dict] = []


@tool
def memory_read(query: str) -> str:
    """Search memories saved from previous conversations.
    Use this to recall user preferences, previously discussed topics, or important context.

    Args:
        query: Keywords or topic to search for.
    """
    if not _memory_store:
        return "No saved memories found."

    query_lower = query.lower()
    matches = []
    for mem in _memory_store:
        content_lower = mem["content"].lower()
        if any(word in content_lower for word in query_lower.split()):
            matches.append(mem)

    if not matches:
        return f"No memories found related to '{query}'."

    formatted = []
    for mem in matches:
        formatted.append(
            f"[{mem['memory_type']}] ({mem['created_at']})\n{mem['content']}"
        )
    return "\n\n".join(formatted)


@tool
def memory_write(content: str, memory_type: str = "context") -> str:
    """Save important information to long-term memory.
    Use this to remember user preferences, key decisions, or context for later reference.

    Args:
        content: Content to remember.
        memory_type: Memory type - "fact", "preference", or "context".
    """
    memory_entry = {
        "content": content,
        "memory_type": memory_type,
        "created_at": datetime.now().isoformat(),
    }
    _memory_store.append(memory_entry)
    return f"Memory saved: [{memory_type}] {content[:50]}..."


def get_memory_store() -> list[dict]:
    """Return current memory store (for testing)."""
    return _memory_store


def clear_memory_store() -> None:
    """Clear all memories (for testing)."""
    _memory_store.clear()
