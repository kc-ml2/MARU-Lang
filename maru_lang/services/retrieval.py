"""Team-scoped retrieval orchestration shared by every transport."""
from __future__ import annotations

from maru_lang.core.relation_db.models.auth import User
from maru_lang.core.relation_db.models.documents import TeamStorageLink
from maru_lang.ports.retrieval import RetrievalBackend, RetrievalQuery, RetrievedChunk
from maru_lang.services.authorization import require_team_member


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
        await require_team_member(team_id, user)

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

        # Keep authorization independent from ranking implementation details.
        # Reject any result outside the storage scope computed by MARU.
        allowed = set(storage_ids)
        if any(result.storage_id not in allowed for result in results):
            raise RuntimeError("Retrieval backend returned an unauthorized storage")
        return results
