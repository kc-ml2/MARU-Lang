"""Summarize node — persist the turn now, generate summaries in the background.

All paths (generate / score / reason) converge on this terminal node. It persists
the Conversation row synchronously (so the turn — and its references — always
exist before the graph ends), then generates the turn/session summaries in a
background task and backfills them. This keeps the slow summary LLM calls off the
critical path, so the WebSocket 'complete' fires as soon as the answer is done
instead of waiting on two extra LLM round-trips. No-op when session_id/user_id
are absent (tests/CLI).

The next turn's context builder tolerates a not-yet-filled summary: it reads
`conv.summary or conv.answer`, so a turn referenced before its summary lands
falls back to the raw answer (no loss). The only eventual-consistency window is
the rolling session summary, which the recent-turns memory window already covers
verbatim.
"""
import asyncio
import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from maru_lang.constants import TURN_SUMMARY_PROMPT, SESSION_SUMMARY_PROMPT
from maru_lang.core.relation_db.models.auth import User
from maru_lang.core.relation_db.models.llm import Llm
from maru_lang.services.chat import create_conversation
from maru_lang.services.session import get_session, update_session_summary
from maru_lang.graph.rag.state import RagState

logger = logging.getLogger(__name__)

# Strong references to in-flight summary backfills. asyncio only keeps weak refs
# to tasks, so without this a backfill could be garbage-collected mid-run. Tasks
# remove themselves on completion; drain_summary_tasks awaits them (shutdown/tests).
_background_tasks: set[asyncio.Task] = set()


def _spawn_background(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def drain_summary_tasks() -> None:
    """Await every in-flight summary backfill (graceful shutdown / tests)."""
    if _background_tasks:
        await asyncio.gather(*list(_background_tasks), return_exceptions=True)


def make_summarize_node(llm: BaseChatModel):
    """Terminal node: persist the turn, then backfill summaries in the background."""

    async def _summarize(prompt: str) -> str:
        try:
            response = await llm.ainvoke(prompt)
            return (response.content or "").strip()
        except Exception:
            return ""

    async def summarize_node(state: RagState) -> dict:
        session_id = state.get("session_id")
        user_id = state.get("user_id")
        # Gate: skip persisting when there's no session+user to save to.
        if not (session_id and user_id):
            return {}

        session = await get_session(session_id)
        user = await User.get_or_none(id=user_id)
        if session is None or user is None:
            return {}

        question = state.get("question")
        if not question:
            humans = [m for m in state.get("messages", []) if isinstance(m, HumanMessage)]
            question = humans[0].content if humans else ""
        answer = state.get("answer") or ""

        # 이 턴이 실제로 돌린 LLM (감사 기록). name -> Llm row.
        llm_name = state.get("llm_name")
        llm_used = await Llm.get_or_none(name=llm_name) if llm_name else None

        # Persist the turn synchronously with an empty summary. The row + its
        # references exist before the graph returns, so 'complete' can fire now
        # and the next turn can always reference this turn (raw-answer fallback
        # until the summary lands).
        conv = await create_conversation(
            user=user,
            session=session,
            question=question,
            answer=answer,
            references=state.get("retrieved_documents") or [],
            summary=None,
            feedback_score=state.get("feedback_score"),
            feedback_reason=state.get("feedback_reason"),
            llm_used=llm_used,
        )

        prev = session.summary or ""

        async def _backfill() -> None:
            # Slow part, off the critical path: build the turn + rolling session
            # summaries and write them back onto the row / session created above.
            try:
                turn_summary = await _summarize(
                    TURN_SUMMARY_PROMPT.format(question=question, answer=answer)
                )
                session_summary = await _summarize(
                    SESSION_SUMMARY_PROMPT.format(previous=prev or "(없음)", question=question, answer=answer)
                ) or prev

                if turn_summary:
                    conv.summary = turn_summary
                    await conv.save(update_fields=["summary"])
                await update_session_summary(session, session_summary)
            except Exception:
                logger.exception("Summary backfill failed (session=%s)", session_id)

        _spawn_background(_backfill())
        return {}

    return summarize_node
