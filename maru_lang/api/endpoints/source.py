"""DocumentSource API endpoints."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from maru_lang.dependencies.auth import get_user, User
from maru_lang.services.admin import is_admin_user
from maru_lang.schemas.source import SyncResponse
from maru_lang.services.source import sync_source

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sources",
    tags=["Sources"],
)


@router.post("/{source_id}/sync", response_model=SyncResponse)
async def sync_source_endpoint(
    source_id: int,
    team_id: int = Query(None, description="Sync only this team's connection"),
    user: User = Depends(get_user),
):
    """Manually trigger sync for a DocumentSource (system admin only)."""
    if not await is_admin_user(user):
        raise HTTPException(status_code=403, detail="Admin access required")
    try:
        result = await sync_source(source_id, team_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return SyncResponse(
        source_id=result["source_id"],
        source_path=result["source_path"],
        status=result["status"],
        files_processed=result["files_processed"],
        files_new=result["files_new"],
        files_updated=result["files_updated"],
        files_deleted=result["files_deleted"],
        error=result["error"],
    )
