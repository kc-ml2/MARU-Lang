import pytest

from maru_lang.core.relation_db.models.auth import Team, TeamMember, User
from maru_lang.core.relation_db.models.documents import TeamStorageLink
from maru_lang.services.storage import (
    connect_storage,
    create_source_storage,
    disconnect_storage,
    get_writable_storage,
)
from maru_lang.utils import file_storage

pytestmark = pytest.mark.asyncio


def _configure(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from maru_lang.services import storage as storage_service

    config = SimpleNamespace(
        team_storage=SimpleNamespace(base_path=str(tmp_path))
    )
    monkeypatch.setattr(file_storage, "get_config", lambda: config)
    monkeypatch.setattr(storage_service, "get_config", lambda: config)


async def test_storage_owner_can_write_and_linked_team_is_read_only(tmp_path, monkeypatch):
    _configure(monkeypatch, tmp_path)
    user = await User.create(name="admin", email="storage-admin@test.local")
    owner = await Team.create(name="Storage Owner", manager=user)
    linked = await Team.create(name="Storage Reader", manager=user)
    await TeamMember.create(user=user, team=owner, role="admin")
    await TeamMember.create(user=user, team=linked, role="admin")

    storage = await create_source_storage(owner, "Shared policies")
    assert file_storage.get_source_storage_dir(storage.id).is_dir()
    assert (await get_writable_storage(owner.id, storage.id)).id == storage.id

    await connect_storage(storage.id, linked.id, user)
    assert await TeamStorageLink.exists(team_id=linked.id, storage_id=storage.id)
    with pytest.raises(PermissionError, match="읽기 전용"):
        await get_writable_storage(linked.id, storage.id)


async def test_disconnect_rejects_owner_connection(tmp_path, monkeypatch):
    _configure(monkeypatch, tmp_path)
    user = await User.create(name="owner", email="storage-owner@test.local")
    team = await Team.create(name="Owner Team", manager=user)
    await TeamMember.create(user=user, team=team, role="admin")
    storage = await create_source_storage(team)

    with pytest.raises(ValueError, match="소유 팀"):
        await disconnect_storage(storage.id, team.id, user)
