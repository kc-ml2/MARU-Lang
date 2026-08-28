"""System-owned read-only storage lifecycle."""
from pathlib import Path

from maru_lang.core.relation_db.models.auth import Team
from maru_lang.core.relation_db.models.documents import SourceStorage, TeamStorageLink
from maru_lang.enums import StorageOwnerType
from maru_lang.utils.document import new_ulid
from maru_lang.utils.file_storage import provision_source_storage

HELP_STORAGE_KEY = "help"


async def ensure_system_storages(root: Path) -> list[SourceStorage]:
    """Create built-in system storages and reconcile their filesystem paths."""
    help_storage, _ = await SourceStorage.get_or_create(
        system_key=HELP_STORAGE_KEY,
        defaults={
            "id": new_ulid(),
            "name": "MARU 도움말",
            "owner_type": StorageOwnerType.SYSTEM,
            "owner_team": None,
            "auto_attach": True,
        },
    )
    await provision_system_storage(root, help_storage)
    return [help_storage]


async def provision_system_storage(root: Path, storage: SourceStorage) -> Path:
    """Materialize a system storage under ``<root>/system/<system_key>``."""
    if (
        storage.owner_type != StorageOwnerType.SYSTEM
        or storage.owner_team_id is not None
        or not storage.system_key
    ):
        raise ValueError("유효하지 않은 시스템 스토리지입니다")
    path = root / "system" / storage.system_key
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("시스템 스토리지 경로가 안전한 디렉터리가 아닙니다")
    return path


async def attach_default_system_storages(team: Team) -> None:
    """Attach every auto-attach system storage to a personal workspace."""
    storage_ids = await SourceStorage.filter(
        owner_type=StorageOwnerType.SYSTEM,
        auto_attach=True,
    ).values_list("id", flat=True)
    for storage_id in storage_ids:
        await TeamStorageLink.get_or_create(team=team, storage_id=storage_id)


async def reconcile_system_storage_links() -> int:
    """Backfill default system storage links for every personal workspace."""
    teams = await Team.filter(is_personal=True)
    for team in teams:
        await attach_default_system_storages(team)
    return len(teams)
