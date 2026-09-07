"""HTTP delivery for short-lived file-download URLs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from maru_lang.context import AppContext
from maru_lang.dependencies.context import get_app_context
from maru_lang.services.download import resolve_download

router = APIRouter(prefix="/files", tags=["Files"])


@router.get("/download", response_class=FileResponse)
async def download_file(
    token: str = Query(...),
    context: AppContext = Depends(get_app_context),
):
    """Start a download when its signed URL is still valid."""
    try:
        path = await resolve_download(context, token)
    except (PermissionError, ValueError):
        # Do not disclose which user, team, storage, or path failed validation.
        raise HTTPException(status_code=403, detail="Invalid or expired download URL")
    except (FileNotFoundError, OSError):
        raise HTTPException(status_code=410, detail="File is no longer available")

    # Expiration is checked before this response starts. A transfer that began
    # in time is not interrupted if the URL expires while bytes are in flight.
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
