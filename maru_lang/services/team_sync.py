"""Synchronize independent source storages into team-scoped ingest projections."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from maru_lang.configs import get_config
from maru_lang.constants import INGEST_TASK_NAME
from maru_lang.core.relation_db.models.auth import Team
from maru_lang.core.relation_db.models.documents import (
    Document,
    SourceStorage,
    TeamStorageLink,
)
from maru_lang.enums.documents import DocumentStatus, IN_FLIGHT_DOCUMENT_STATUSES
from maru_lang.graph.ingest.loader import is_supported
from maru_lang.services.document import get_or_create_upload_group
from maru_lang.services.ingest import finalize_document_deletion
from maru_lang.utils.document import (
    is_team_storage_metadata,
    make_storage_source_fingerprint,
    new_ulid,
    team_storage_metadata,
)
from maru_lang.utils.file_storage import provision_source_storage

logger = logging.getLogger(__name__)
Enqueue = Callable[[str, int], Awaitable[None]]


@dataclass
class TeamSyncResult:
    team_id: int
    storage_id: str | None = None
    discovered: int = 0
    queued: int = 0
    unchanged: int = 0
    unstable: int = 0
    deleted: int = 0
    errors: list[str] = field(default_factory=list)


def _iter_source_files(storage_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in storage_dir.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and not any(
            part.startswith(".") for part in path.relative_to(storage_dir).parts
        )
        and is_supported(path)
    )


async def sync_team_storage(
    team_id: int,
    storage_id: str,
    *,
    enqueue: Enqueue | None = None,
    now: float | None = None,
) -> TeamSyncResult:
    """Reconcile one linked storage into one team's Document projection."""
    cfg = get_config()
    if not cfg.team_storage.base_path:
        raise ValueError("team_storage.base_path가 설정되지 않았습니다")
    link = await TeamStorageLink.get_or_none(
        team_id=team_id, storage_id=storage_id
    ).select_related("storage")
    if link is None:
        raise LookupError("팀에 연결된 스토리지를 찾을 수 없습니다")
    storage_dir = await asyncio.to_thread(provision_source_storage, storage_id)
    if storage_dir is None:
        raise ValueError("팀 저장 공간이 비활성화되어 있습니다")

    result = TeamSyncResult(team_id=team_id, storage_id=storage_id)
    current_paths: set[str] = set()
    current_time = time.time() if now is None else now

    for source in await asyncio.to_thread(_iter_source_files, storage_dir):
        relative_path = source.relative_to(storage_dir).as_posix()
        current_paths.add(relative_path)
        result.discovered += 1
        try:
            stat = source.stat()
            if current_time - stat.st_mtime < cfg.team_storage.stable_for_seconds:
                result.unstable += 1
                continue
            fingerprint = make_storage_source_fingerprint(
                team_id, storage_id, relative_path, stat.st_size, stat.st_mtime_ns
            )
            doc = await Document.get_or_none(
                file_path=relative_path,
                storage_id=storage_id,
                group__team_id=team_id,
            )
            if doc is not None and doc.source_fingerprint == fingerprint:
                result.unchanged += 1
                continue
            if doc is not None and doc.status in IN_FLIGHT_DOCUMENT_STATUSES:
                result.unstable += 1
                continue

            if doc is None:
                folder_path = Path(relative_path).parent.as_posix()
                if folder_path == ".":
                    folder_path = ""
                group = await get_or_create_upload_group(team_id, folder_path)
                doc = await Document.create(
                    id=new_ulid(),
                    name=source.stem,
                    group=group,
                    storage_id=storage_id,
                    file_path=relative_path,
                    storage_path=None,
                    file_size=stat.st_size,
                    source_fingerprint=fingerprint,
                    status=DocumentStatus.UPLOADING,
                    metadata=team_storage_metadata(source.name),
                )
            else:
                doc.name = source.stem
                doc.storage_path = None
                doc.file_size = stat.st_size
                doc.source_fingerprint = fingerprint
                doc.status = DocumentStatus.UPLOADING
                doc.error_message = None
                doc.metadata = team_storage_metadata(source.name, doc.metadata)
                await doc.save()

            if enqueue is not None:
                await enqueue(doc.id, team_id)
            result.queued += 1
        except Exception as exc:
            logger.exception(
                "Storage sync failed: team=%s storage=%s file=%s",
                team_id, storage_id, relative_path,
            )
            result.errors.append(f"{relative_path}: {exc}")

    managed = await Document.filter(
        group__team_id=team_id, storage_id=storage_id
    ).all()
    for doc in managed:
        if not is_team_storage_metadata(doc.metadata) or doc.file_path in current_paths:
            continue
        if doc.status in IN_FLIGHT_DOCUMENT_STATUSES:
            continue
        await finalize_document_deletion(doc.id)
        result.deleted += 1
    return result


async def sync_team_folder(
    team_id: int,
    *,
    enqueue: Enqueue | None = None,
    now: float | None = None,
) -> TeamSyncResult:
    """Compatibility aggregate: sync every storage connected to a team."""
    if await Team.get_or_none(id=team_id) is None:
        raise LookupError("팀을 찾을 수 없습니다")
    links = await TeamStorageLink.filter(team_id=team_id).all()
    total = TeamSyncResult(team_id=team_id)
    for link in links:
        result = await sync_team_storage(
            team_id, link.storage_id, enqueue=enqueue, now=now
        )
        for key in ("discovered", "queued", "unchanged", "unstable", "deleted"):
            setattr(total, key, getattr(total, key) + getattr(result, key))
        total.errors.extend(result.errors)
    return total


async def enqueue_team_document(app, document_id: str, team_id: int) -> None:
    arq = getattr(app.state, "arq", None)
    if arq is not None:
        await arq.enqueue_job(INGEST_TASK_NAME, document_id, team_id)
        return
    from maru_lang.services.ingest import run_ingest_for_document
    doc = await Document.get(id=document_id)
    await run_ingest_for_document(doc, team_id)


async def run_team_sync_loop(app) -> None:
    cfg = get_config()
    interval = cfg.team_storage.scan_interval_seconds
    if not cfg.team_storage.base_path or interval <= 0:
        return

    async def enqueue(document_id: str, team_id: int) -> None:
        try:
            await enqueue_team_document(app, document_id, team_id)
        except Exception:
            logger.exception("Team ingest submission failed: %s", document_id)

    while True:
        try:
            links = await TeamStorageLink.all()
            for link in links:
                result = await sync_team_storage(
                    link.team_id, link.storage_id, enqueue=enqueue
                )
                if result.queued or result.deleted or result.errors:
                    logger.info("Team storage sync: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Team storage sync cycle failed")
        await asyncio.sleep(interval)
