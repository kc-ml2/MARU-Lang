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


def resolve_source_storage_path(
    root: Path,
    storage_id: str,
    relative_path: str,
    *,
    provision: bool = False,
) -> Path:
    storage_dir = (
        provision_source_storage(root, storage_id)
        if provision
        else get_source_storage_dir(root, storage_id)
    )
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("잘못된 스토리지 파일 경로입니다")
    destination = storage_dir / relative
    if not destination.resolve().is_relative_to(storage_dir.resolve()):
        raise ValueError("스토리지 밖의 경로는 사용할 수 없습니다")
    return destination


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
