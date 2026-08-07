"""Tests for the safe CLI remove command helpers."""

from unittest.mock import AsyncMock, patch

import pytest
import typer

from maru_lang.commands.remove import _remove_document, _remove_group
from maru_lang.core.relation_db.models.auth import Team, User
from maru_lang.core.relation_db.models.documents import Document, DocumentGroup
from maru_lang.enums.documents import DocumentStatus


async def _document(path: str = "policies/security.pdf") -> tuple[Team, DocumentGroup, Document]:
    manager = await User.create(name="Admin", email="remove-admin@example.com")
    team = await Team.create(name="RemoveTeam", manager=manager)
    group = await DocumentGroup.create(name="policies", team=team)
    doc = await Document.create(
        id="doc-remove-1",
        name="security",
        group=group,
        file_path=path,
        status=DocumentStatus.ACTIVE,
    )
    return team, group, doc


@pytest.mark.asyncio
async def test_remove_document_accepts_exact_path_and_uses_safe_service():
    team, _group, doc = await _document()
    delete = AsyncMock()

    with patch("maru_lang.commands.remove.delete_document_by_id", delete):
        await _remove_document(doc.file_path, team.id, force=True)

    delete.assert_awaited_once_with(doc.id, team.id, user_id=None)


@pytest.mark.asyncio
async def test_remove_document_rejects_cross_team_target():
    _team, _group, doc = await _document()
    other_manager = await User.create(name="Other", email="other-remove@example.com")
    other_team = await Team.create(name="OtherRemoveTeam", manager=other_manager)

    with pytest.raises(typer.Exit) as exc:
        await _remove_document(doc.id, other_team.id, force=True)

    assert exc.value.exit_code == 1


@pytest.mark.asyncio
async def test_remove_group_uses_subtree_service():
    team, group, _doc = await _document()
    delete = AsyncMock(return_value={"deleted": 1, "deferred": 0, "group_removed": True})

    with patch("maru_lang.commands.remove.delete_group_documents", delete):
        await _remove_group(group.id, team.id, force=True)

    delete.assert_awaited_once_with(group.id, team.id, user_id=None)
