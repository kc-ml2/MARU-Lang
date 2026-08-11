"""Materialize zero-byte Google-native files exposed by an rclone mount."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


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
        if "rclone" not in mount_info and not (
            "fuse" in mount_info and ":" in source
        ):
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


@contextmanager
def materialize_rclone_file(path: Path) -> Iterator[Path]:
    """Yield readable content for a possibly zero-byte rclone mount entry.

    Ordinary files, and zero-byte files outside an identifiable rclone mount,
    are yielded unchanged. A zero-byte rclone entry is downloaded with
    ``rclone copyto`` into a temporary directory and removed on context exit.
    This handles Google Docs/Slides/Sheets exports whose FUSE stat size is zero.
    """
    path = path.resolve()
    if path.stat().st_size != 0:
        yield path
        return

    remote_path = _rclone_remote_path(path)
    if remote_path is None:
        yield path
        return
    if shutil.which("rclone") is None:
        raise RuntimeError(f"rclone executable not found while downloading {path}")

    temp_dir = Path(tempfile.mkdtemp(prefix="maru-rclone-"))
    destination = temp_dir / path.name
    try:
        result = subprocess.run(
            ["rclone", "copyto", remote_path, str(destination)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown rclone error"
            raise RuntimeError(f"rclone download failed for {path.name}: {detail}")
        if not destination.is_file() or destination.stat().st_size == 0:
            raise RuntimeError(f"rclone downloaded an empty file for {path.name} ({remote_path})")
        yield destination
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
