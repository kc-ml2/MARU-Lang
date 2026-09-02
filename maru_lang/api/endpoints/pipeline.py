"""Pipeline inspection and controlled rerun endpoints shared conceptually with MCP."""
from fastapi import APIRouter, Depends, HTTPException

from maru_lang.context import AppContext
from maru_lang.core.relation_db.models import PipelineRun, TeamMember, TeamStorageLink
from maru_lang.dependencies.auth import get_user
from maru_lang.dependencies.context import get_app_context
from maru_lang.pipeline import PipelineConfig
from maru_lang.schemas.pipeline import (
    PipelineConfigPayload,
    PipelineInspectionResponse,
    PipelineRunResponse,
    RerunPipelineRequest,
)
from maru_lang.services.pipeline import (
    configure_pipeline,
    inspect_pipeline,
    request_pipeline_run,
)

router = APIRouter(tags=["Pipeline"])


def _run_response(run: PipelineRun) -> PipelineRunResponse:
    return PipelineRunResponse(
        id=run.id,
        storage_id=run.storage_id,
        from_stage=run.from_stage.value,
        status=run.status.value,
        config_snapshot=PipelineConfigPayload(**run.config_snapshot),
        report=run.report,
        error=run.error,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


@router.get(
    "/teams/{team_id}/storages/{storage_id}/pipeline",
    response_model=PipelineInspectionResponse,
)
async def get_pipeline(
    team_id: int,
    storage_id: str,
    user=Depends(get_user),
):
    try:
        inspection = await inspect_pipeline(storage_id, team_id, user)
        return PipelineInspectionResponse(
            storage_id=inspection.storage_id,
            stages=list(inspection.stages),
            config=PipelineConfigPayload(**inspection.config.to_dict()),
            latest_run_id=inspection.latest_run_id,
            latest_run_status=inspection.latest_run_status,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.put(
    "/storages/{storage_id}/pipeline/config",
    response_model=PipelineConfigPayload,
)
async def update_pipeline_config(
    storage_id: str,
    body: PipelineConfigPayload,
    user=Depends(get_user),
):
    try:
        config = PipelineConfig.from_dict(body.model_dump())
        saved = await configure_pipeline(storage_id, user, config)
        return PipelineConfigPayload(**saved.to_dict())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post(
    "/storages/{storage_id}/pipeline/runs",
    response_model=PipelineRunResponse,
    status_code=201,
)
async def rerun_pipeline(
    storage_id: str,
    body: RerunPipelineRequest,
    user=Depends(get_user),
    context: AppContext = Depends(get_app_context),
):
    try:
        run = await request_pipeline_run(
            storage_id, user, body.from_stage, context.indexing
        )
        return _run_response(run)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get(
    "/teams/{team_id}/pipeline/runs/{run_id}", response_model=PipelineRunResponse
)
async def get_pipeline_run(team_id: int, run_id: str, user=Depends(get_user)):
    run = await PipelineRun.get_or_none(id=run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Pipeline run을 찾을 수 없습니다")
    if not await TeamMember.exists(team_id=team_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="해당 팀의 멤버가 아닙니다")
    if not await TeamStorageLink.exists(team_id=team_id, storage_id=run.storage_id):
        raise HTTPException(status_code=403, detail="Pipeline run에 접근할 수 없습니다")
    return _run_response(run)
