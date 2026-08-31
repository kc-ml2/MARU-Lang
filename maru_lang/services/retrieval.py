"""Team-scoped retrieval orchestration shared by every transport."""
from __future__ import annotations

from maru_lang.core.relation_db.models.auth import TeamMember, User
from maru_lang.core.relation_db.models.documents import TeamStorageLink
from maru_lang.ports.retrieval import RetrievalBackend, RetrievalQuery, RetrievedChunk


class RetrievalService:
    """Resolve team access before delegating ranking to a retrieval backend."""

    def __init__(self, backend: RetrievalBackend) -> None:
        self._backend = backend

    async def search(
        self,
        *,
        team_id: int,
        user: User,
        text: str,
        limit: int = 10,
        filters: dict[str, object] | None = None,
    ) -> list[RetrievedChunk]:
        if not await TeamMember.exists(team_id=team_id, user_id=user.id):
            raise PermissionError("해당 팀의 멤버가 아닙니다")

        storage_ids = tuple(
            await TeamStorageLink.filter(team_id=team_id).values_list(
                "storage_id", flat=True
            )
        )
        query = RetrievalQuery(
            text=text,
            storage_ids=storage_ids,
            limit=limit,
            filters=filters or {},
        )
        if not storage_ids:
            return []
        results = list(await self._backend.search(query))

        # A backend may be remote or independently operated. Enforce the
        # authorized storage boundary again before returning its results.
        allowed = set(storage_ids)
        if any(result.storage_id not in allowed for result in results):
            raise RuntimeError("Retrieval backend returned an unauthorized storage")
        return results
