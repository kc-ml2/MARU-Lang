"""Trusted local operator operations; never expose without system authentication."""
from pathlib import Path

from maru_lang.core.relation_db.models.auth import Team
from maru_lang.core.relation_db.models.documents import SourceStorage, TeamStorageLink
from maru_lang.enums import StorageOwnerType
from maru_lang.utils.ids import new_ulid


def validate_external_path(path: Path, managed_root: Path) -> Path:
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('An absolute existing directory is required')
    resolved = path.resolve(strict=True)
    if resolved != path or not resolved.is_dir():
        raise ValueError('Symlinks and non-directories are not supported')
    managed = managed_root.resolve()
    if resolved == managed or managed in resolved.parents or resolved in managed.parents:
        raise ValueError('External storage must not overlap the MARU filesystem root')
    return resolved


async def register_external(root: Path, path: Path, name: str) -> SourceStorage:
    resolved = validate_external_path(path, root)
    if not name.strip():
        raise ValueError('Storage name is required')
    for existing in await SourceStorage.filter(storage_type='external'):
        other = Path(existing.external_path)
        if resolved == other or resolved in other.parents or other in resolved.parents:
            raise ValueError('External storage paths must not overlap')
    storage_id = new_ulid()
    return await SourceStorage.create(
        id=storage_id, name=name.strip(), storage_type='external',
        external_path=str(resolved), owner_type=StorageOwnerType.SYSTEM,
        owner_team=None, system_key=f'external-{storage_id}', auto_attach=False,
    )


async def external_storage(storage_id: str) -> SourceStorage:
    storage = await SourceStorage.get_or_none(id=storage_id)
    if storage is None:
        raise ValueError('Storage not found')
    if storage.storage_type != 'external' or storage.owner_type != StorageOwnerType.SYSTEM:
        raise ValueError('This operation only supports system-managed external storage')
    return storage


async def share_external(storage_id: str, team_id: int) -> None:
    await external_storage(storage_id)
    if not await Team.exists(id=team_id):
        raise ValueError('Team not found')
    await TeamStorageLink.get_or_create(storage_id=storage_id, team_id=team_id)


async def unshare_external(storage_id: str, team_id: int) -> None:
    await external_storage(storage_id)
    await TeamStorageLink.filter(storage_id=storage_id, team_id=team_id).delete()


async def unregister_external(storage_id: str) -> None:
    storage = await external_storage(storage_id)
    if await TeamStorageLink.exists(storage_id=storage_id):
        raise ValueError('Remove all team shares before unregistering storage')
    # Metadata only. Never provision, remove, or modify external filesystem data.
    await storage.delete()
