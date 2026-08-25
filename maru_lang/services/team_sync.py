"""Synchronize team-owned source folders into the ingest pipeline."""
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
from maru_lang.core.relation_db.models.documents import Document
from maru_lang.enums.documents import DocumentStatus
from maru_lang.graph.ingest.loader import is_supported
from maru_lang.services.document import get_or_create_upload_group
from maru_lang.services.ingest import finalize_document_deletion
from maru_lang.utils.document import make_source_fingerprint_for_file, new_ulid
from maru_lang.utils.file_storage import get_team_source_dir

logger = logging.getLogger(__name__)

Enqueue = Callable[[str, int], Awaitable[None]]


@dataclass
class TeamSyncResult:
    team_id: int
    discovered: int = 0
    queued: int = 0
    unchanged: int = 0
    unstable: int = 0
    deleted: int = 0
    errors: list[str] = field(default_factory=list)


def _fingerprint(team_id: int, relative_path: str, size: int, mtime_ns: int) -> str:
    return make_source_fingerprint_for_file(
        f"{team_id}:{relative_path}", size, mtime_ns
    )


def _iter_source_files(team_dir: Path) -> list[Path]:
    return sorted(
        path for path in team_dir.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and not any(part.startswith(".") for part in path.relative_to(team_dir).parts)
        and is_supported(path)
    )


async def sync_team_folder(
    team_id: int,
    *,
    enqueue: Enqueue | None = None,
    now: float | None = None,
) -> TeamSyncResult:
    """Reconcile one team's source folder with Document rows.

    New/changed stable files are registered for direct source ingest and passed
    to ``enqueue``. Missing files are deleted only when their
    document is terminal; in-flight files are left for a later scan to avoid
    racing an active worker.
    """
    cfg = get_config()
    if not cfg.team_storage.base_path:
        raise ValueError("team_storage.base_path가 설정되지 않았습니다")

    team = await Team.get_or_none(id=team_id)
    if team is None:
        raise LookupError("팀을 찾을 수 없습니다")
    team_dir = get_team_source_dir(team.id, team.name)
    if team_dir is None:
        raise ValueError("팀 저장 공간이 비활성화되어 있습니다")
    team_dir.mkdir(parents=True, exist_ok=True)

    result = TeamSyncResult(team_id=team_id)
    current_paths: set[str] = set()
    current_time = time.time() if now is None else now

    for source in await asyncio.to_thread(_iter_source_files, team_dir):
        relative_path = source.relative_to(team_dir).as_posix()
        current_paths.add(relative_path)
        result.discovered += 1
        try:
            stat = source.stat()
            if current_time - stat.st_mtime < cfg.team_storage.stable_for_seconds:
                result.unstable += 1
                continue
            fingerprint = _fingerprint(
                team_id, relative_path, stat.st_size, stat.st_mtime_ns
            )
            doc = await Document.get_or_none(
                file_path=relative_path, group__team_id=team_id
            )
            if doc is not None and doc.source_fingerprint == fingerprint:
                result.unchanged += 1
                continue
            if doc is not None and doc.status in (
                DocumentStatus.UPLOADING,
                DocumentStatus.PROCESSING,
                DocumentStatus.DELETING,
            ):
                # Serialize revisions: the next scan will pick the changed file
                # after the current job reaches a terminal state.
                result.unstable += 1
                continue

            doc_id = doc.id if doc is not None else new_ulid()
            if doc is None:
                folder_path = Path(relative_path).parent.as_posix()
                if folder_path == ".":
                    folder_path = ""
                group = await get_or_create_upload_group(team_id, folder_path)
                doc = await Document.create(
                    id=doc_id,
                    name=source.stem,
                    group=group,
                    file_path=relative_path,
                    storage_path=None,
                    file_size=stat.st_size,
                    source_fingerprint=fingerprint,
                    status=DocumentStatus.UPLOADING,
                    metadata={"original_filename": source.name, "source": "team_storage"},
                )
            else:
                doc.name = source.stem
                doc.storage_path = None
                doc.file_size = stat.st_size
                doc.source_fingerprint = fingerprint
                doc.status = DocumentStatus.UPLOADING
                doc.error_message = None
                doc.metadata = {
                    **(doc.metadata or {}),
                    "original_filename": source.name,
                    "source": "team_storage",
                }
                await doc.save()

            if enqueue is not None:
                await enqueue(doc.id, team_id)
            result.queued += 1
        except Exception as exc:
            logger.exception("Team folder sync failed: team=%s file=%s", team_id, relative_path)
            result.errors.append(f"{relative_path}: {exc}")

    # Only managed team-storage documents participate in absence deletion, so
    # legacy/API-only rows cannot be erased by enabling this feature.
    team_documents = await Document.filter(group__team_id=team_id).all()
    managed = [
        doc for doc in team_documents
        if (doc.metadata or {}).get("source") == "team_storage"
    ]
    for doc in managed:
        if doc.file_path in current_paths:
            continue
        if doc.status in (
            DocumentStatus.UPLOADING,
            DocumentStatus.PROCESSING,
            DocumentStatus.DELETING,
        ):
            continue
        await finalize_document_deletion(doc.id)
        result.deleted += 1

    return result


async def run_team_sync_loop(app) -> None:
    """Periodic scanner. Queue mode enqueues; otherwise ingests sequentially."""
    cfg = get_config()
    interval = cfg.team_storage.scan_interval_seconds
    if not cfg.team_storage.base_path or interval <= 0:
        return

    async def enqueue(document_id: str, team_id: int) -> None:
        arq = getattr(app.state, "arq", None)
        if arq is not None:
            await arq.enqueue_job(INGEST_TASK_NAME, document_id, team_id)
            return
        from maru_lang.services.ingest import run_ingest_for_document
        doc = await Document.get(id=document_id)
        try:
            await run_ingest_for_document(doc, team_id)
        except Exception:
            # run_ingest_for_document records status/audit; one bad document
            # must not stop the scanner.
            logger.exception("In-process team ingest failed: %s", document_id)

    while True:
        try:
            for team_id in await Team.all().values_list("id", flat=True):
                result = await sync_team_folder(int(team_id), enqueue=enqueue)
                if result.queued or result.deleted or result.errors:
                    logger.info("Team folder sync: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Team folder sync cycle failed")
        await asyncio.sleep(interval)
