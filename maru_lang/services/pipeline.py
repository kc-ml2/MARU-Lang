"""Inspect, configure, and selectively rerun MARU's stable pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from maru_lang.core.relation_db.models import (
    PipelineRun,
    SourceStorage,
    StoragePipelineConfig,
    TeamMember,
    TeamStorageLink,
    User,
)
from maru_lang.enums import PipelineRunStatus, PipelineStage, StorageOwnerType
from maru_lang.pipeline import PIPELINE_STAGES, PipelineConfig
from maru_lang.ports.indexing import PipelineExecutor
from maru_lang.services.authorization import require_team_admin
from maru_lang.utils.ids import new_ulid


@dataclass(frozen=True, slots=True)
class PipelineInspection:
    storage_id: str
    stages: tuple[str, ...]
    config: PipelineConfig
    config_hash: str
    configured: bool
    latest_run_id: str | None
    latest_run_status: str | None


async def get_pipeline_config(storage_id: str) -> PipelineConfig:
    storage = await SourceStorage.get_or_none(id=storage_id)
    if storage is None:
        raise LookupError("스토리지를 찾을 수 없습니다")
    saved = await StoragePipelineConfig.get_or_none(storage_id=storage_id)
    return PipelineConfig.from_dict(saved.config if saved else None)


async def inspect_pipeline(
    storage_id: str, team_id: int, requester: User
) -> PipelineInspection:
    if not await TeamMember.exists(team_id=team_id, user_id=requester.id):
        raise PermissionError("해당 팀의 멤버가 아닙니다")
    if not await TeamStorageLink.exists(storage_id=storage_id, team_id=team_id):
        raise PermissionError("해당 팀에서 접근할 수 없는 스토리지입니다")
    saved = await StoragePipelineConfig.get_or_none(storage_id=storage_id)
    config = PipelineConfig.from_dict(saved.config if saved else None)
    latest = await PipelineRun.filter(storage_id=storage_id).order_by(
        "-created_at"
    ).first()
    return PipelineInspection(
        storage_id=storage_id,
        stages=tuple(stage.value for stage in PIPELINE_STAGES),
        config=config,
        config_hash=config.fingerprint,
        configured=saved is not None,
        latest_run_id=latest.id if latest else None,
        latest_run_status=latest.status.value if latest else None,
    )


async def configure_pipeline(
    storage_id: str,
    requester: User,
    config: PipelineConfig,
) -> PipelineConfig:
    storage = await SourceStorage.get_or_none(id=storage_id)
    if storage is None:
        raise LookupError("스토리지를 찾을 수 없습니다")
    if storage.owner_type != StorageOwnerType.TEAM:
        raise PermissionError("시스템 스토리지 설정은 변경할 수 없습니다")
    assert storage.owner_team_id is not None
    await require_team_admin(storage.owner_team_id, requester)
    await StoragePipelineConfig.update_or_create(
        storage_id=storage_id,
        defaults={"config": config.to_dict(), "config_hash": config.fingerprint},
    )
    return config


async def request_pipeline_run(
    storage_id: str,
    requester: User,
    from_stage: PipelineStage,
    indexing: PipelineExecutor | None,
) -> PipelineRun:
    storage = await SourceStorage.get_or_none(id=storage_id)
    if storage is None:
        raise LookupError("스토리지를 찾을 수 없습니다")
    if storage.owner_type != StorageOwnerType.TEAM:
        raise PermissionError("시스템 스토리지는 재실행할 수 없습니다")
    assert storage.owner_team_id is not None
    await require_team_admin(storage.owner_team_id, requester)
    if indexing is None:
        raise RuntimeError("Indexing pipeline is not configured")
    if from_stage != PipelineStage.SCAN:
        raise RuntimeError("Selective pipeline reruns are not configured")
    if await PipelineRun.exists(
        storage_id=storage_id,
        status__in=[PipelineRunStatus.PENDING, PipelineRunStatus.RUNNING],
    ):
        raise RuntimeError("이미 실행 중인 indexing run이 있습니다")

    config = await get_pipeline_config(storage_id)
    run = await PipelineRun.create(
        id=new_ulid(),
        storage_id=storage_id,
        requested_by=requester,
        from_stage=from_stage,
        config_snapshot=config.to_dict(),
        config_hash=config.fingerprint,
    )
    run.status = PipelineRunStatus.RUNNING
    run.started_at = datetime.now(timezone.utc)
    await run.save(update_fields=["status", "started_at"])
    try:
        report = await indexing.execute(storage_id, config, from_stage)
    except Exception as exc:
        run.status = PipelineRunStatus.FAILED
        run.error = str(exc)
        run.completed_at = datetime.now(timezone.utc)
        await run.save(update_fields=["status", "error", "completed_at"])
        raise
    run.status = PipelineRunStatus.COMPLETED
    run.report = {
        "storage_id": report.storage_id,
        "documents_seen": report.documents_seen,
        "chunks_written": report.chunks_written,
        "documents_deleted": report.documents_deleted,
    }
    run.completed_at = datetime.now(timezone.utc)
    await run.save(update_fields=["status", "report", "completed_at"])
    return run
