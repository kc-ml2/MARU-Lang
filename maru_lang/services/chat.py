from typing import Dict, List
from maru_lang.core.vector_db.retrieve_document import RetrieveDocument
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
) -> List[Dict[str, str]] | None:
    return await Conversation.filter(
        user=user,
        created_at__gte=start_date,
    ).order_by(
        'created_at'
    ).prefetch_related(
        'references'
    ).values('question', 'answer')[:limit]

async def create_conversation(
    user: User,
    question: str,
    answer: str,
    references: list[RetrieveDocument],
    enhanced_question: str | None = None,
):
    conversation = await Conversation.create(
        user=user,
        question=question,
        answer=answer,
        enhanced_question=enhanced_question,
    )

    # Use a set to avoid creating duplicate references
    seen_doc_ids = set()

    for reference in references:
        # Extract document_id from metadata
        doc_id = reference.metadata.get("document_id")
        if not doc_id or doc_id in seen_doc_ids:
            continue

        # Ensure the document still exists
        document = await Document.get_or_none(id=doc_id)
        if document:
            await ConversationReference.create(
                conversation=conversation,
                document=document,
                score=reference.score,
            )
            seen_doc_ids.add(doc_id)