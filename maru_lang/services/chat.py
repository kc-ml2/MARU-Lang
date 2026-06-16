from typing import List
from maru_lang.core.relation_db.models.chat import Conversation, ConversationReference, Session
from maru_lang.core.relation_db.models.documents import Document
from maru_lang.core.relation_db.models.auth import User
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
) -> List[Conversation]:
    """Fetch the session's recent conversations, newest first (for memory context)."""
    return await Conversation.filter(
        session_id=session_id,
    ).order_by("-created_at").limit(limit).all()


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
    """
    conversation = await Conversation.create(
        user=user,
        session=session,
        question=question,
        answer=answer,
        enhanced_question=enhanced_question,
        summary=summary,
        feedback_score=feedback_score,
        feedback_reason=feedback_reason,
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