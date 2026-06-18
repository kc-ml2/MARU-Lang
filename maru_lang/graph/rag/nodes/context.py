"""Context builder node — assemble prior memory into a single context string.

Because each turn uses a fresh thread_id, the checkpointer does not carry
previous turns. This entry node rebuilds memory from the DB — the user's
persistent facts/preferences (UserMemory) plus the session's rolling summary
and recent turns — into `memory_context`, which route/generate then share.
"""
from maru_lang.services.chat import fetch_recent_conversations_by_session
from maru_lang.services.memory import format_user_memory
from maru_lang.services.session import get_session
from maru_lang.graph.rag.state import RagState


def make_context_builder_node(recent_turns: int = 3):
    """Build the context-builder node bound to a memory window (recent_turns)."""

    async def context_builder_node(state: RagState) -> dict:
        """Assemble user memory + prior session turns into `memory_context`."""
        parts: list[str] = []
        style_directive = ""

        user_id = state.get("user_id")
        if user_id:
            facts_block, style_directive = await format_user_memory(user_id)
            if facts_block:
                parts.append(facts_block)

        session_id = state.get("session_id")
        if session_id:
            session = await get_session(session_id)
            if session and session.summary:
                parts.append(f"[이전 대화 요약]\n{session.summary}")

            recent = await fetch_recent_conversations_by_session(session_id, limit=recent_turns)
            for conv in reversed(recent):  # oldest → newest
                answer = conv.summary or conv.answer
                parts.append(f"Q: {conv.question}\nA: {answer}")

        return {"memory_context": "\n\n".join(parts), "style_directive": style_directive}

    return context_builder_node
