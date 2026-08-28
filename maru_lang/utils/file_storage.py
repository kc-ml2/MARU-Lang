"""Safe filesystem paths for source storages."""
import shutil
from pathlib import Path


def get_team_storage_root(root: Path) -> Path:
    return root / "storages"


def get_source_storage_dir(root: Path, storage_id: str) -> Path:
    return get_team_storage_root(root) / storage_id


def provision_source_storage(root: Path, storage_id: str) -> Path:
    """Create a team-owned source directory."""
    storage_dir = get_source_storage_dir(root, storage_id)
    storage_dir.parent.mkdir(parents=True, exist_ok=True)
    storage_dir.mkdir(exist_ok=True)
    if not storage_dir.is_dir() or storage_dir.is_symlink():
        raise ValueError("원본 저장소 경로가 안전한 디렉터리가 아닙니다")
    return storage_dir


def remove_source_storage(root: Path, storage_id: str) -> bool:
    storage_dir = get_source_storage_dir(root, storage_id)
    if not storage_dir.exists():
        return False
    storage_root = get_team_storage_root(root)
    if storage_dir.parent.resolve() != storage_root.resolve():
        raise ValueError("잘못된 원본 스토리지 경로입니다")
    if not storage_dir.is_dir() or storage_dir.is_symlink():
        raise ValueError("원본 스토리지 경로가 디렉터리가 아닙니다")
    shutil.rmtree(storage_dir)
    return True
