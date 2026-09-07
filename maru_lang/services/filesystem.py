"""Deterministic, bounded filesystem metadata operations."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from maru_lang.core.relation_db.models.auth import User
from maru_lang.core.relation_db.models.documents import SourceStorage, TeamStorageLink
from maru_lang.services.authorization import require_team_member
from maru_lang.utils.file_storage import get_storage_dir


@dataclass(frozen=True, slots=True)
class FileEntry:
    path: str
    type: Literal["file", "directory", "symlink"]
    size: int | None
    modified_at_ns: int


@dataclass(frozen=True, slots=True)
class SearchResult:
    results: tuple[dict[str, object], ...]
    truncated: bool


async def authorized_storage_root(
    filesystem_root: Path,
    *,
    team_id: int,
    storage_id: str,
    requester: User,
) -> Path:
    """Resolve a storage root only after enforcing team membership and linkage."""
    await require_team_member(team_id, requester)
    link = await TeamStorageLink.get_or_none(
        team_id=team_id, storage_id=storage_id
    ).select_related("storage")
    if link is None:
        raise PermissionError("해당 팀은 스토리지에 접근할 수 없습니다")
    storage: SourceStorage = link.storage
    return get_storage_dir(filesystem_root, storage).resolve(strict=True)


def _relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value or ".")
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("path must be relative and must not contain '..'")
    return path


def resolve_within(root: Path, relative_path: str = ".") -> Path:
    """Resolve a path while preventing traversal and symlink escapes."""
    resolved_root = root.resolve(strict=True)
    candidate = (resolved_root / _relative_path(relative_path)).resolve(strict=True)
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError("path escapes the storage root")
    return candidate


def stat_path(root: Path, *, path: str) -> dict[str, object]:
    """Return filesystem metadata without following the final symlink."""
    storage_root = root.resolve(strict=True)
    relative = _relative_path(path)
    unresolved = storage_root / relative
    if unresolved.is_symlink():
        stat = unresolved.lstat()
        return {
            "path": relative.as_posix(),
            "type": "symlink",
            "size": None,
            "modified_at_ns": stat.st_mtime_ns,
        }
    target = resolve_within(storage_root, path)
    stat = target.stat()
    return {
        "path": relative.as_posix(),
        "type": "directory" if target.is_dir() else "file",
        "size": None if target.is_dir() else stat.st_size,
        "modified_at_ns": stat.st_mtime_ns,
    }



def list_tree(
    root: Path,
    *,
    path: str = ".",
    max_depth: int = 2,
    max_results: int = 500,
) -> SearchResult:
    """Return a stable, depth-limited tree without following symlinks."""
    if not 0 <= max_depth <= 20:
        raise ValueError("max_depth must be between 0 and 20")
    if not 1 <= max_results <= 10_000:
        raise ValueError("max_results must be between 1 and 10000")

    storage_root = root.resolve(strict=True)
    start = resolve_within(storage_root, path)
    if not start.is_dir():
        raise ValueError("path is not a directory")

    entries: list[FileEntry] = []
    pending: list[tuple[Path, int]] = [(start, 0)]
    truncated = False
    while pending:
        directory, depth = pending.pop(0)
        children = sorted(directory.iterdir(), key=lambda child: child.name)
        directories: list[tuple[Path, int]] = []
        for child in children:
            stat = child.lstat()
            relative = child.relative_to(storage_root).as_posix()
            if child.is_symlink():
                kind: Literal["file", "directory", "symlink"] = "symlink"
                size = None
            elif child.is_dir():
                kind = "directory"
                size = None
                if depth < max_depth:
                    directories.append((child, depth + 1))
            else:
                kind = "file"
                size = stat.st_size
            entries.append(FileEntry(relative, kind, size, stat.st_mtime_ns))
            if len(entries) > max_results:
                truncated = True
                break
        if truncated:
            break
        pending.extend(directories)

    entries = sorted(entries[:max_results], key=lambda entry: entry.path)
    return SearchResult(tuple(asdict(entry) for entry in entries), truncated)
