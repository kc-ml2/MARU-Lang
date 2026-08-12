"""rclone provider for the generic file-materialization layer."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from maru_lang.graph.ingest.constants import RCLONE_PLACEHOLDER_EXTENSIONS
from maru_lang.graph.ingest.materialization.base import Materialization


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _mount_from_findmnt(path: Path) -> tuple[str, Path] | None:
    """Find an rclone mount on Linux."""
    if shutil.which("findmnt") is None:
        return None
    try:
        result = subprocess.run(
            ["findmnt", "--json", "--target", str(path), "--output", "SOURCE,TARGET,FSTYPE"],
            check=True,
            capture_output=True,
            text=True,
        )
        mounts = json.loads(result.stdout).get("filesystems", [])
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None

    if not mounts or "rclone" not in str(mounts[0].get("fstype", "")).lower():
        return None
    source = str(mounts[0].get("source", ""))
    target = str(mounts[0].get("target", ""))
    return (source, Path(target)) if source and target else None


def _mount_from_mount_command(path: Path) -> tuple[str, Path] | None:
    """Find an rclone/macFUSE mount on systems without findmnt (notably macOS)."""
    try:
        result = subprocess.run(["mount"], check=True, capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return None

    resolved = path.resolve()
    candidates: list[tuple[str, Path]] = []
    for line in result.stdout.splitlines():
        match = re.match(r"^(.*?) on (.*?) \((.*?)\)$", line)
        if not match:
            continue
        source, target_text, options = match.groups()
        # macOS rclone mounts normally report macfuse; Linux reports fuse.rclone.
        # A colon-bearing source distinguishes an rclone remote from other FUSE mounts.
        mount_info = options.lower()
        if "rclone" not in mount_info and not ("fuse" in mount_info and ":" in source):
            continue
        target = Path(target_text.replace("\\040", " ")).resolve()
        if _is_relative_to(resolved, target):
            candidates.append((source, target))

    return max(candidates, key=lambda item: len(item[1].parts), default=None)


def _rclone_remote_path(path: Path) -> str | None:
    """Map a mounted local path to its ``remote:path`` rclone object name."""
    mount = _mount_from_findmnt(path) or _mount_from_mount_command(path)
    if mount is None:
        return None

    source, target = mount
    try:
        relative = path.resolve().relative_to(target.resolve()).as_posix()
    except ValueError:
        return None
    separator = "" if source.endswith((":", "/")) else "/"
    return f"{source}{separator}{relative}"


def resolve_rclone_materialization(path: Path) -> Materialization | None:
    """Prepare retrieval for a zero-byte placeholder on an rclone mount.

    The generic materializer owns temporary-file lifecycle. This provider owns
    only the rclone-specific condition, remote-path lookup, and copy action.
    """
    if (
        path.stat().st_size != 0
        or path.suffix.lower() not in RCLONE_PLACEHOLDER_EXTENSIONS
    ):
        return None

    remote_path = _rclone_remote_path(path)
    if remote_path is None:
        return None
    if shutil.which("rclone") is None:
        raise RuntimeError(f"rclone executable not found while downloading {path}")

    def copy_to(destination: Path) -> None:
        result = subprocess.run(
            ["rclone", "copyto", remote_path, str(destination)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown rclone error"
            raise RuntimeError(f"rclone download failed for {path.name}: {detail}")

    return Materialization(
        provider="rclone",
        write_to=copy_to,
        validate=lambda destination: destination.is_file() and destination.stat().st_size > 0,
    )
