from fastapi import APIRouter, Depends, HTTPException

from maru_lang.context import AppContext
from maru_lang.dependencies.context import get_app_context
from maru_lang.dependencies.auth import get_user
from maru_lang.core.relation_db.models.auth import Team
from maru_lang.schemas.storage import (
    CreateStorageRequest,
    StorageResponse,
)
from maru_lang.services.storage import (
    connect_storage,
    create_source_storage,
    delete_source_storage,
    disconnect_storage,
    list_team_storages,
)
from maru_lang.services.authorization import require_team_admin, require_team_member

router = APIRouter(tags=["Storages"])


def _response(storage, team_id: int) -> StorageResponse:
    owner_team = getattr(storage, "owner_team", None)
    return StorageResponse(
        id=storage.id,
        name=storage.name,
        owner_type=storage.owner_type,
        owner_team_id=storage.owner_team_id,
        owner_team_name=owner_team.name if owner_team else None,
        access="owner" if storage.owner_team_id == team_id else "read",
    )


@router.get("/teams/{team_id}/storages", response_model=list[StorageResponse])
async def get_team_storages(team_id: int, user=Depends(get_user)):
    try:
        await require_team_member(team_id, user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return [_response(storage, team_id) for storage in await list_team_storages(team_id)]


@router.post("/teams/{team_id}/storages", response_model=StorageResponse, status_code=201)
async def create_storage(
    team_id: int,
    body: CreateStorageRequest,
    user=Depends(get_user),
    context: AppContext = Depends(get_app_context),
):
    try:
        await require_team_admin(team_id, user)
        team = await Team.get(id=team_id)
        storage = await create_source_storage(
            context.settings.filesystem_root, team, body.name
        )
        await storage.fetch_related("owner_team")
        return _response(storage, team_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.post(
    "/teams/{team_id}/storages/{storage_id}/connect",
    response_model=StorageResponse,
)
async def connect_team_storage(
    team_id: int, storage_id: str, user=Depends(get_user)
):
    try:
        link = await connect_storage(storage_id, team_id, user)
        await link.fetch_related("storage", "storage__owner_team")
        return _response(link.storage, team_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/teams/{team_id}/storages/{storage_id}", status_code=204)
async def disconnect_team_storage(
    team_id: int,
    storage_id: str,
    user=Depends(get_user),
):
    try:
        await disconnect_storage(storage_id, team_id, user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.delete("/storages/{storage_id}", status_code=204)
async def delete_storage(
    storage_id: str,
    user=Depends(get_user),
    context: AppContext = Depends(get_app_context),
):
    try:
        await delete_source_storage(
            context.settings.filesystem_root, storage_id, user
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
