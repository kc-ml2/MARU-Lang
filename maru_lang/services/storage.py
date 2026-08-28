"""Independent source-storage ownership and team connections."""
from __future__ import annotations

import asyncio

from pathlib import Path
from maru_lang.core.relation_db.models.auth import Team, User
from maru_lang.core.relation_db.models.documents import (
    SourceStorage,
    TeamStorageLink,
)
from maru_lang.enums import StorageOwnerType
from maru_lang.utils.ids import new_ulid
from maru_lang.utils.file_storage import provision_source_storage, remove_source_storage


async def create_source_storage(
    root: Path,
    owner_team: Team,
    name: str | None = None,
) -> SourceStorage:
    """Create storage owned by a team and connect that team to it."""
    storage = await SourceStorage.create(
        id=new_ulid(),
        name=(name or owner_team.name),
        owner_type=StorageOwnerType.TEAM,
        owner_team=owner_team,
    )
    try:
        await asyncio.to_thread(provision_source_storage, root, storage.id)
        await TeamStorageLink.create(team=owner_team, storage=storage)
    except Exception:
        await storage.delete()
        raise
    return storage


async def ensure_default_source_storage(root: Path, team: Team) -> SourceStorage:
    """Return a team's oldest owned storage, bootstrapping one when enabled."""
    storage = await SourceStorage.filter(
        owner_type=StorageOwnerType.TEAM, owner_team_id=team.id
    ).order_by("created_at").first()
    if storage is None:
        return await create_source_storage(root, team, f"{team.name} storage")
    await asyncio.to_thread(provision_source_storage, root, storage.id)
    await TeamStorageLink.get_or_create(team=team, storage=storage)
    return storage


async def list_team_storages(team_id: int) -> list[SourceStorage]:
    links = await TeamStorageLink.filter(team_id=team_id).select_related(
        "storage", "storage__owner_team"
    )
    return [link.storage for link in links]


async def connect_storage(
    storage_id: str, target_team_id: int, requester: User
) -> TeamStorageLink:
    """Connect storage read-only; requester must admin both owner and target."""
    from maru_lang.services.team import _check_admin

    storage = await SourceStorage.get_or_none(id=storage_id)
    if storage is None:
        raise LookupError("스토리지를 찾을 수 없습니다")
    if storage.owner_type != StorageOwnerType.TEAM:
        raise PermissionError("시스템 스토리지는 자동 연결만 허용됩니다")
    assert storage.owner_team_id is not None
    await _check_admin(storage.owner_team_id, requester)
    await _check_admin(target_team_id, requester)
    link, _ = await TeamStorageLink.get_or_create(
        team_id=target_team_id, storage_id=storage_id
    )
    return link


async def disconnect_storage(
    storage_id: str, team_id: int, requester: User
) -> None:
    """Remove a team's read-only access without touching shared documents."""
    from maru_lang.services.team import _check_admin

    storage = await SourceStorage.get_or_none(id=storage_id)
    if storage is None:
        raise LookupError("스토리지를 찾을 수 없습니다")
    if storage.owner_type == StorageOwnerType.SYSTEM:
        raise PermissionError("시스템 스토리지 연결은 해제할 수 없습니다")
    if storage.owner_team_id == team_id:
        raise ValueError("소유 팀은 스토리지 연결을 해제할 수 없습니다")
    await _check_admin(team_id, requester)
    assert storage.owner_team_id is not None
    await _check_admin(storage.owner_team_id, requester)

    # Documents belong to the storage, not to the linked team. Disconnecting a
    # reader therefore removes only the permission link and never shared data.
    await TeamStorageLink.filter(team_id=team_id, storage_id=storage_id).delete()


async def delete_source_storage(
    root: Path, storage_id: str, requester: User
) -> None:
    """Delete an unshared storage owned by requester's admin team."""
    from maru_lang.services.team import _check_admin

    storage = await SourceStorage.get_or_none(id=storage_id)
    if storage is None:
        raise LookupError("스토리지를 찾을 수 없습니다")
    if storage.owner_type != StorageOwnerType.TEAM:
        raise PermissionError("시스템 스토리지는 삭제할 수 없습니다")
    assert storage.owner_team_id is not None
    await _check_admin(storage.owner_team_id, requester)
    if await TeamStorageLink.filter(storage_id=storage_id).exclude(
        team_id=storage.owner_team_id
    ).exists():
        raise ValueError("연결된 팀이 있는 스토리지는 삭제할 수 없습니다")
    await asyncio.to_thread(remove_source_storage, root, storage_id)
    await storage.delete()
