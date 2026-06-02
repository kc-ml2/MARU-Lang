"""Summarize node — generate summaries and persist the turn at the end.

All paths (generate / score / reason) converge on this terminal node. It builds
a turn summary and a rolling session summary, then creates the Conversation row
and updates Session.summary. No-op when session_id/user_id are absent (tests/CLI).
"""
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from maru_lang.constants import TURN_SUMMARY_PROMPT, SESSION_SUMMARY_PROMPT
from maru_lang.core.relation_db.models.auth import User
from maru_lang.core.relation_db.models.chat import Session
from maru_lang.services.chat import create_conversation
from maru_lang.graph.rag.state import RagState


def make_summarize_node(llm: BaseChatModel):
    """Terminal node: build turn/session summaries and persist them to the DB."""

    async def _summarize(prompt: str) -> str:
        try:
            response = await llm.ainvoke(prompt)
            return (response.content or "").strip()
        except Exception:
            return ""

    async def summarize_node(state: RagState) -> dict:
        session_id = state.get("session_id")
        user_id = state.get("user_id")
        # Gate: skip summarizing/persisting when there's no session+user to save to.
        if not (session_id and user_id):
            return {}

        session = await Session.get_or_none(id=session_id)
        user = await User.get_or_none(id=user_id)
        if session is None or user is None:
            return {}

        question = state.get("question")
        if not question:
            humans = [m for m in state.get("messages", []) if isinstance(m, HumanMessage)]
            question = humans[0].content if humans else ""
        answer = state.get("answer") or ""

        turn_summary = await _summarize(
            TURN_SUMMARY_PROMPT.format(question=question, answer=answer)
        )
        prev = session.summary or ""
        session_summary = await _summarize(
            SESSION_SUMMARY_PROMPT.format(previous=prev or "(없음)", question=question, answer=answer)
        ) or prev

        await create_conversation(
            user=user,
            session=session,
            question=question,
            answer=answer,
            references=state.get("retrieved_documents") or [],
            summary=turn_summary or None,
            feedback_score=state.get("feedback_score"),
            feedback_reason=state.get("feedback_reason"),
        )

        session.summary = session_summary
        await session.save()

        return {}

    return summarize_node
