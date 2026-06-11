"""Config endpoint - client initialization data."""
from fastapi import APIRouter

from maru_lang.graph.ingest.parser import ingestible_extensions
from maru_lang.schemas.config import ConfigResponse

router = APIRouter(
    prefix="/config",
    tags=["Config"],
)


@router.get("", response_model=ConfigResponse)
async def get_config():
    """Return client initialization config.

    supported_extensions reflects the CURRENT parser config — KorDoc-only
    formats (hwp/hwpx/hwpml) are listed only when the KorDoc parser is enabled,
    so upload UIs offer exactly what this server can ingest.
    """
    return ConfigResponse(
        supported_extensions=sorted(ingestible_extensions()),
    )
