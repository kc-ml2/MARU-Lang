"""Short-lived, signed file-download capabilities."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode

from maru_lang.context import AppContext
from maru_lang.core.relation_db.models.auth import User
from maru_lang.services.filesystem import authorized_storage_root, resolve_within

DOWNLOAD_TOKEN_TYPE = "file_download"


def _regular_file(root: Path, path: str) -> Path:
    unresolved = root.resolve(strict=True) / path
    if unresolved.is_symlink():
        raise ValueError("path is not a regular file")
    target = resolve_within(root, path)
    if not target.is_file():
        raise ValueError("path is not a regular file")
    return target


async def create_download_url(
    context: AppContext,
    *,
    requester: User,
    team_id: int,
    storage_id: str,
    path: str,
    expires_in_seconds: int | None = None,
) -> dict[str, object]:
    """Issue a URL whose permission to start a download expires shortly.

    Expiration is checked when an HTTP download request begins; it is not a
    transfer timeout and does not interrupt a response already in progress.
    """
    lifetime = (
        context.settings.download_url_expire_seconds
        if expires_in_seconds is None
        else expires_in_seconds
    )
    if not 30 <= lifetime <= 900:
        raise ValueError("expires_in_seconds must be between 30 and 900")

    root = await authorized_storage_root(
        context.settings.filesystem_root,
        team_id=team_id,
        storage_id=storage_id,
        requester=requester,
    )
    target = _regular_file(root, path)
    stat = target.stat()
    relative_path = target.relative_to(root).as_posix()
    token, expires_at = context.tokens.create(
        {
            "typ": DOWNLOAD_TOKEN_TYPE,
            "sub": str(requester.id),
            "team_id": team_id,
            "storage_id": storage_id,
            "path": relative_path,
            "size": stat.st_size,
            "modified_at_ns": stat.st_mtime_ns,
        },
        timedelta(seconds=lifetime),
    )
    return {
        "url": f"{context.settings.public_url}/files/download?{urlencode({'token': token})}",
        "path": relative_path,
        "size": stat.st_size,
        "modified_at_ns": stat.st_mtime_ns,
        "url_expires_at": expires_at.isoformat(),
        "url_valid_for_seconds": lifetime,
    }


async def resolve_download(
    context: AppContext,
    token: str,
) -> Path:
    """Validate a capability, current authorization, and the bound file version."""
    payload = context.tokens.decode(token)
    if payload is None or payload.get("typ") != DOWNLOAD_TOKEN_TYPE:
        raise PermissionError("invalid or expired download URL")
    try:
        user_id = int(payload["sub"])
        team_id = int(payload["team_id"])
        storage_id = str(payload["storage_id"])
        path = str(payload["path"])
        expected_size = int(payload["size"])
        expected_modified_at_ns = int(payload["modified_at_ns"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PermissionError("invalid download URL") from exc

    user = await User.get_or_none(id=user_id)
    if user is None:
        raise PermissionError("download user no longer exists")
    root = await authorized_storage_root(
        context.settings.filesystem_root,
        team_id=team_id,
        storage_id=storage_id,
        requester=user,
    )
    target = _regular_file(root, path)
    stat = target.stat()
    if stat.st_size != expected_size or stat.st_mtime_ns != expected_modified_at_ns:
        raise FileNotFoundError("file changed after the download URL was issued")
    return target
