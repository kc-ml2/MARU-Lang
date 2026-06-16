"""Service-level tests for upsert_document_from_file (CLI sync path).

Identity and fingerprint must be team-scoped: the same file path synced by
different teams becomes separate, team-private documents instead of colliding on
the global file_path / unique source_fingerprint column.
"""
import pytest

from maru_lang.core.relation_db.models.auth import User, Team
from maru_lang.core.relation_db.models.documents import Document, DocumentGroup
from maru_lang.services.document import upsert_document_from_file


async def _team_with_group(name: str) -> DocumentGroup:
    mgr = await User.create(name=f"{name}-mgr", email=f"{name}@example.com")
    team = await Team.create(name=name, manager=mgr, is_private=False)
    return await DocumentGroup.create(name="uploads", team=team)


class TestUpsertTeamScope:

    async def test_same_path_different_teams_are_separate_documents(self):
        """Two teams syncing the identical path/size/mtime get distinct docs."""
        group_a = await _team_with_group("teamA")
        group_b = await _team_with_group("teamB")
        path = "/mnt/shared/handbook.pdf"

        doc_a, created_a = await upsert_document_from_file(
            group=group_a, name="handbook", path=path, size=100, mtime_ns=111
        )
        doc_b, created_b = await upsert_document_from_file(
            group=group_b, name="handbook", path=path, size=100, mtime_ns=111
        )

        assert created_a and created_b
        assert doc_a.id != doc_b.id
        assert doc_a.group_id == group_a.id
        assert doc_b.group_id == group_b.id
        # Identical path/size/mtime but team-scoped -> different fingerprints,
        # so no unique collision and no cross-team document hijack.
        assert doc_a.source_fingerprint != doc_b.source_fingerprint
        assert await Document.all().count() == 2

    async def test_same_team_same_path_is_idempotent(self):
        """Re-syncing an unchanged file in the same team reuses the document."""
        group = await _team_with_group("teamC")
        path = "/data/x.pdf"

        doc1, _ = await upsert_document_from_file(
            group=group, name="x", path=path, size=10, mtime_ns=1
        )
        doc2, needs_processing = await upsert_document_from_file(
            group=group, name="x", path=path, size=10, mtime_ns=1
        )

        assert doc1.id == doc2.id
        assert needs_processing is False
        assert await Document.all().count() == 1
