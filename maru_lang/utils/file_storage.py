"""Team source-folder and legacy private file-storage utilities."""
import os
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO

from maru_lang.configs import get_config


def get_storage_dir() -> Path:
    """Get the absolute storage directory from config."""
    cfg = get_config()
    p = Path(cfg.storage_dir)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p


def get_document_dir(team_id: int, doc_id: str) -> Path:
    """Get the legacy private storage directory for a specific document."""
    return get_storage_dir() / str(team_id) / doc_id


def get_team_storage_root() -> Path | None:
    """Return the configured team-source root, or None when disabled."""
    base_path = get_config().team_storage.base_path
    if not base_path:
        return None
    root = Path(base_path).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    return root


def team_storage_key(team_id: int, team_name: str = "") -> str:
    """Stable directory key. Team names are display-only and may change."""
    return str(team_id)


def get_team_source_dir(team_id: int, team_name: str) -> Path | None:
    root = get_team_storage_root()
    return None if root is None else root / team_storage_key(team_id, team_name)


def provision_team_storage(team_id: int, team_name: str) -> Path | None:
    """Create a team source directory when team storage is configured.

    A sole legacy ``<id>-<name>`` directory is migrated to ``<id>``. Ambiguous
    layouts fail rather than merging user files automatically.
    """
    team_dir = get_team_source_dir(team_id, team_name)
    if team_dir is None:
        return None
    if not team_dir.exists():
        legacy = list(team_dir.parent.glob(f"{team_id}-*")) if team_dir.parent.exists() else []
        if len(legacy) == 1 and legacy[0].is_dir() and not legacy[0].is_symlink():
            legacy[0].rename(team_dir)
        elif len(legacy) > 1:
            raise ValueError(f"팀 {team_id}의 기존 저장소 폴더가 여러 개입니다")
        else:
            team_dir.mkdir(parents=True, exist_ok=True)
    if not team_dir.is_dir() or team_dir.is_symlink():
        raise ValueError("팀 원본 저장소 경로가 안전한 디렉터리가 아닙니다")
    return team_dir


def _safe_team_source_path(team_id: int, team_name: str, relative_path: str) -> Path:
    team_dir = provision_team_storage(team_id, team_name)
    if team_dir is None:
        raise ValueError("team_storage.base_path가 설정되지 않았습니다")
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("잘못된 팀 파일 경로입니다")
    destination = team_dir.joinpath(relative)
    if destination.resolve().parent != team_dir.resolve() and team_dir.resolve() not in destination.resolve().parents:
        raise ValueError("팀 저장소 밖의 경로는 사용할 수 없습니다")
    return destination


def save_team_source_upload(
    upload_file: BinaryIO,
    filename: str,
    team_id: int,
    team_name: str,
    folder_path: str = "",
) -> Path:
    """Atomically place an API upload in the team's source-of-truth folder."""
    relative_path = str(Path(folder_path) / filename) if folder_path else filename
    destination = _safe_team_source_path(team_id, team_name, relative_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".part", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            while chunk := upload_file.read(8192):
                output.write(chunk)
        os.replace(temp_name, destination)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    return destination


def save_file(source: Path, team_id: int, doc_id: str) -> str:
    """Copy a local file to permanent storage.

    Args:
        source: Source file path.
        team_id: Team ID.
        doc_id: Document ID.

    Returns:
        Absolute path to the stored file.
    """
    dest_dir = get_document_dir(team_id, doc_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"original{source.suffix}"
    shutil.copy2(source, dest)
    return str(dest.absolute())


def remove_document_storage(storage_path: str | None, doc_id: str) -> None:
    """Best-effort removal of a document's storage dir (…/<team>/<doc_id>/).

    Guarded: only removes when the parent directory is actually named after the
    document id, so a mis-set storage_path can never wipe an unrelated folder.
    """
    if not storage_path:
        return
    doc_dir = Path(storage_path).parent
    if doc_dir.name == doc_id and doc_dir.is_dir():
        shutil.rmtree(doc_dir, ignore_errors=True)


def remove_team_source_storage(team_id: int, team_name: str) -> bool:
    """Remove a team-owned source directory only when explicitly configured."""
    team_dir = get_team_source_dir(team_id, team_name)
    if team_dir is None or not team_dir.exists():
        return False
    root = get_team_storage_root()
    assert root is not None
    if team_dir.parent.resolve() != root.resolve():
        raise ValueError("잘못된 팀 원본 저장소 경로입니다")
    if not team_dir.is_dir() or team_dir.is_symlink():
        raise ValueError("팀 원본 저장소 경로가 디렉터리가 아닙니다")
    shutil.rmtree(team_dir)
    return True


def remove_team_storage(team_id: int) -> bool:
    """Remove a team's complete legacy private storage directory.

    Unlike per-document best-effort cleanup, failures propagate so a team delete
    cannot report success while leaving its whole storage tree behind.
    """
    storage_dir = get_storage_dir().resolve()
    team_dir = storage_dir / str(team_id)
    if team_dir.parent.resolve() != storage_dir:
        raise ValueError("잘못된 팀 저장소 경로입니다")
    if not team_dir.exists():
        return False
    if not team_dir.is_dir() or team_dir.is_symlink():
        raise ValueError("팀 저장소 경로가 디렉터리가 아닙니다")
    shutil.rmtree(team_dir)
    return True


async def save_upload(upload_file: BinaryIO, filename: str, team_id: int, doc_id: str) -> str:
    """Save an upload for legacy deployments without team_storage.

    Args:
        upload_file: File-like object to read from.
        filename: Original filename (for extension).
        team_id: Team ID.
        doc_id: Document ID.

    Returns:
        Absolute path to the stored file.
    """
    ext = Path(filename).suffix
    dest_dir = get_document_dir(team_id, doc_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"original{ext}"

    with open(dest, "wb") as f:
        while chunk := upload_file.read(8192):
            f.write(chunk)

    return str(dest.absolute())
