"""Chat session service.

A Session is the durable, queryable record of a LangGraph thread
(``session.id == thread_id``). The server owns session id generation.
"""
import uuid

from maru_lang.core.relation_db.models.auth import User
from maru_lang.core.relation_db.models.chat import Session
from maru_lang.enums.chat import SessionStatus


async def create_session(
    user: User,
    title: str | None = None,
    metadata: dict | None = None,
) -> Session:
    """Create a new chat session owned by ``user``.

    The session id (= LangGraph thread_id) is a server-generated uuid hex.
    """
    return await Session.create(
        id=uuid.uuid4().hex,
        user=user,
        title=title,
        metadata=metadata or {},
    )


async def get_session_for_user(session_id: str, user: User) -> Session | None:
    """Return the session if it exists, is owned by ``user``, and is not deleted."""
    session = await Session.get_or_none(id=session_id, user=user)
    if session is None or session.status == SessionStatus.DELETED:
        return None
    return session


async def get_session(session_id: str) -> Session | None:
    """Return a session by id (no ownership/status filter).

    For access-controlled lookups use get_session_for_user; this is the plain
    id lookup the graph uses to rebuild/persist a thread's memory.
    """
    return await Session.get_or_none(id=session_id)


async def update_session_summary(session: Session, summary: str) -> None:
    """Persist the rolling conversation summary on a session."""
    session.summary = summary
    await session.save()


def list_sessions_by_user(user: User):
    """User's non-deleted sessions as a QuerySet (newest first; for pagination)."""
    return Session.filter(user=user).exclude(status=SessionStatus.DELETED).order_by("-updated_at")


async def get_last_session(user: User) -> Session | None:
    """Return the user's most recently updated non-deleted session, or None."""
    return (
        await Session.filter(user=user)
        .exclude(status=SessionStatus.DELETED)
        .order_by("-updated_at")
        .first()
    )


async def get_or_create_last_session(user: User) -> Session:
    """Return the user's most recent session, creating a new one if none exists."""
    return await get_last_session(user) or await create_session(user)
