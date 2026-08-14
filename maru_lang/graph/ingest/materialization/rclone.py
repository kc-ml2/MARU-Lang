"""rclone provider for the generic file-materialization layer."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from maru_lang.configs import get_config
from maru_lang.graph.ingest.constants import RCLONE_PLACEHOLDER_EXTENSIONS
from maru_lang.graph.ingest.materialization.base import Materialization


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _configured_mount(path: Path) -> tuple[str, Path] | None:
    """Return the most specific configured mount containing ``path``."""
    resolved = path.resolve()
    candidates = []
    for mount in get_config().ingest_materialization.rclone.mounts:
        target = Path(mount.local_path).expanduser().resolve()
        if _is_relative_to(resolved, target):
            candidates.append((mount.remote, target))
    return max(candidates, key=lambda item: len(item[1].parts), default=None)


def _rclone_remote_path(path: Path) -> str | None:
    """Map a configured local mount path to its rclone object name."""
    mount = _configured_mount(path)
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
        # Never infer an rclone remote from OS mount output. An unconfigured
        # zero-byte document may simply be an empty local file, so leave it to
        # the normal ingest pipeline instead of performing remote I/O.
        return None
    if shutil.which("rclone") is None:
        raise RuntimeError(f"rclone executable not found while downloading {path}")

    def copy_to(destination: Path) -> None:
        command = ["rclone"]
        config_path = get_config().ingest_materialization.rclone.config_path
        if config_path:
            command.extend(["--config", str(Path(config_path).expanduser())])
        command.extend(["copyto", remote_path, str(destination)])
        result = subprocess.run(
            command,
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
