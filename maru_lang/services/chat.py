from typing import Dict, List
from maru_lang.schemas.chat import DocumentReference
from maru_lang.core.relation_db.models.chat import Conversation, ConversationReference
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

async def create_conversation(
    user: User,
    question: str,
    answer: str,
    references: List[DocumentReference],
    enhanced_question: str | None = None,
):
    """
    Create a conversation with references.

    Args:
        user: User who asked the question
        question: User's question
        answer: Generated answer
        references: List of DocumentReference objects
        enhanced_question: Enhanced/rewritten question (optional)
    """
    conversation = await Conversation.create(
        user=user,
        question=question,
        answer=answer,
        enhanced_question=enhanced_question,
    )

    # Use a set to avoid creating duplicate references
    seen_doc_ids = set()

    for reference in references:
        doc_id = reference.document_id
        if not doc_id or doc_id in seen_doc_ids:
            continue

        # TODO FIX score
        score = 0
        # Ensure the document still exists
        document = await Document.get_or_none(id=doc_id)
        if document:
            await ConversationReference.create(
                conversation=conversation,
                document=document,
                score=score,
            )
            seen_doc_ids.add(doc_id)