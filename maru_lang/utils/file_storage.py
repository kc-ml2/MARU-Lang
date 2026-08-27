"""Team source-folder and legacy private file-storage utilities."""
import os
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO



def get_storage_dir(root: Path) -> Path:
    """Return the legacy private-storage directory below the source root."""
    return root / ".maru" / "documents"


def get_document_dir(root: Path, team_id: int, doc_id: str) -> Path:
    """Get the legacy private storage directory for a specific document."""
    return get_storage_dir(root) / str(team_id) / doc_id


def get_team_storage_root(root: Path) -> Path:
    """Return the configured source-storage root."""
    return root


def get_source_storage_dir(root: Path, storage_id: str) -> Path:
    return get_team_storage_root(root) / str(storage_id)


def provision_source_storage(root: Path, storage_id: str, legacy_team_id: int | None = None) -> Path:
    """Create an independent source-storage directory.

    ``legacy_team_id`` migrates the old sole ``<team-id>[-name]`` directory into
    the new storage-ID path while bootstrapping existing teams.
    """
    storage_dir = get_source_storage_dir(root, storage_id)
    if not storage_dir.exists():
        legacy: list[Path] = []
        if legacy_team_id is not None and storage_dir.parent.exists():
            exact = storage_dir.parent / str(legacy_team_id)
            legacy = [exact] if exact.exists() else list(
                storage_dir.parent.glob(f"{legacy_team_id}-*")
            )
        if len(legacy) == 1 and legacy[0].is_dir() and not legacy[0].is_symlink():
            legacy[0].rename(storage_dir)
        elif len(legacy) > 1:
            raise ValueError(
                f"팀 {legacy_team_id}의 기존 저장소 폴더가 여러 개입니다"
            )
        else:
            storage_dir.mkdir(parents=True, exist_ok=True)
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
    """Resolve a relative path below a storage root without allowing escape."""
    team_dir = (
        provision_source_storage(root, storage_id)
        if provision
        else get_source_storage_dir(root, storage_id)
    )
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("잘못된 팀 파일 경로입니다")
    destination = team_dir / relative
    if not destination.resolve().is_relative_to(team_dir.resolve()):
        raise ValueError("팀 저장소 밖의 경로는 사용할 수 없습니다")
    return destination


def save_team_source_upload(
    root: Path,
    upload_file: BinaryIO,
    filename: str,
    storage_id: str,
    folder_path: str = "",
) -> Path:
    """Atomically place an owner upload in a source-of-truth storage."""
    relative_path = str(Path(folder_path) / filename) if folder_path else filename
    destination = resolve_source_storage_path(
        root, storage_id, relative_path, provision=True
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".part", dir=destination.parent
    )
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


def save_file(root: Path, source: Path, team_id: int, doc_id: str) -> str:
    """Copy a local file to permanent storage.

    Args:
        source: Source file path.
        team_id: Team ID.
        doc_id: Document ID.

    Returns:
        Absolute path to the stored file.
    """
    dest_dir = get_document_dir(root, team_id, doc_id)
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


def remove_source_storage(root: Path, storage_id: str) -> bool:
    """Remove an independent source directory only when explicitly requested."""
    team_dir = get_source_storage_dir(root, storage_id)
    if team_dir is None or not team_dir.exists():
        return False
    root = get_team_storage_root(root)
    if team_dir.parent.resolve() != root.resolve():
        raise ValueError("잘못된 팀 원본 저장소 경로입니다")
    if not team_dir.is_dir() or team_dir.is_symlink():
        raise ValueError("팀 원본 저장소 경로가 디렉터리가 아닙니다")
    shutil.rmtree(team_dir)
    return True


def remove_team_storage(root: Path, team_id: int) -> bool:
    """Remove a team's complete legacy private storage directory.

    Unlike per-document best-effort cleanup, failures propagate so a team delete
    cannot report success while leaving its whole storage tree behind.
    """
    storage_dir = get_storage_dir(root).resolve()
    team_dir = storage_dir / str(team_id)
    if team_dir.parent.resolve() != storage_dir:
        raise ValueError("잘못된 팀 저장소 경로입니다")
    if not team_dir.exists():
        return False
    if not team_dir.is_dir() or team_dir.is_symlink():
        raise ValueError("팀 저장소 경로가 디렉터리가 아닙니다")
    shutil.rmtree(team_dir)
    return True


async def save_upload(root: Path, upload_file: BinaryIO, filename: str, team_id: int, doc_id: str) -> str:
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
    dest_dir = get_document_dir(root, team_id, doc_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"original{ext}"

    with open(dest, "wb") as f:
        while chunk := upload_file.read(8192):
            f.write(chunk)

    return str(dest.absolute())
