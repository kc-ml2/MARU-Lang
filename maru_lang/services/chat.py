from typing import List
from maru_lang.core.relation_db.models.chat import Conversation, ConversationReference, Session
from maru_lang.core.relation_db.models.documents import Document
from maru_lang.core.relation_db.models.auth import User
from maru_lang.core.relation_db.models.llm import Llm
from tortoise.queryset import QuerySet
from datetime import datetime
from datetime import timezone


def fetch_conversation_queryset_by_user(
    user: User,
) -> QuerySet[Conversation]:
    return Conversation.filter(
        user=user,
    ).order_by('-created_at')


async def fetch_conversation_by_user_and_date(
    user: User,
    start_date: datetime = datetime.now(timezone.utc),
    limit: int = 3,
) -> List[Conversation] | None:
    """
    Fetch conversations by user and date range.

    Args:
        user: User object
        start_date: Start date for filtering conversations
        limit: Maximum number of conversations to return

    Returns:
        List of Conversation objects or None
    """
    conversations = await Conversation.filter(
        user=user,
        created_at__gte=start_date,
    ).order_by(
        'created_at'
    ).limit(limit).all()

    return conversations if conversations else None

async def fetch_recent_conversations_by_session(
    session_id: str,
    limit: int = 3,
    team_ids: list[int] | None = None,
) -> List[Conversation]:
    """Fetch the session's recent conversations, newest first (for memory context).

    If ``team_ids`` is provided, only conversations whose stored
    ``metadata.team_ids`` are fully contained within the given ids are returned
    (Python-level filter for DB portability). When absent, all conversations for
    the session are returned (backwards-compatible with sessions that have no
    metadata).
    """
    qs = Conversation.filter(session_id=session_id).order_by("-created_at")
    results = await qs.limit(limit * 10).all()  # fetch extra room for filtering

    if team_ids:
        team_ids_set = set(team_ids)
        filtered: list[Conversation] = []
        for conv in results:
            meta = conv.metadata or {}
            conv_teams = meta.get("team_ids") or []
            conv_team_set = set(conv_teams)
            if conv_team_set and conv_team_set.issubset(team_ids_set):
                filtered.append(conv)
        results = filtered[:limit]
    else:
        results = results[:limit]

    return results


def fetch_conversations_by_session(session_id: str):
    """The session's conversations as a QuerySet (chronological; for pagination)."""
    return Conversation.filter(session_id=session_id).order_by("created_at")


async def create_conversation(
    user: User,
    question: str,
    answer: str,
    references: List[dict],
    session: Session | None = None,
    enhanced_question: str | None = None,
    summary: str | None = None,
    feedback_score: int | None = None,
    feedback_reason: str | None = None,
    llm_used: "Llm | None" = None,
    team_ids: list[int] | None = None,
) -> Conversation:
    """
    Create a conversation (one completed graph turn) with its references.

    Args:
        user: User who asked the question
        question: User's question
        answer: Generated answer
        references: Retrieved documents from graph state (list of dicts with
            "document_id" and "score" keys, as produced by the RAG format node)
        session: Owning chat session (LangGraph thread), if any
        enhanced_question: Enhanced/rewritten question (optional)
        feedback_score: User feedback score for this turn (optional)
        feedback_reason: User feedback reason for this turn (optional)
        llm_used: LLM that actually ran this turn (audit record, optional)
        team_ids: Team scope for this turn (stored in metadata for filtering)
    """
    metadata: dict = {}
    if team_ids:
        metadata["team_ids"] = team_ids

    conversation = await Conversation.create(
        user=user,
        session=session,
        question=question,
        answer=answer,
        enhanced_question=enhanced_question,
        summary=summary,
        metadata=metadata,
        feedback_score=feedback_score,
        feedback_reason=feedback_reason,
        llm_used=llm_used,
    )

    # Use a set to avoid creating duplicate references
    seen_doc_ids = set()

    for reference in references:
        doc_id = reference.get("document_id")
        if not doc_id or doc_id in seen_doc_ids:
            continue

        score = reference.get("score") or 0
        # Ensure the document still exists
        document = await Document.get_or_none(id=doc_id)
        if document:
            await ConversationReference.create(
                conversation=conversation,
                document=document,
                score=score,
            )
            seen_doc_ids.add(doc_id)

    return conversation