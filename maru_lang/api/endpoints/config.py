"""Config endpoint - client initialization data."""
from fastapi import APIRouter

from maru_lang.constants import SUPPORTED_EXTENSIONS
from maru_lang.schemas.config import ConfigResponse

router = APIRouter(
    prefix="/config",
    tags=["Config"],
)


@router.get("", response_model=ConfigResponse)
async def get_config():
    """Return client initialization config."""
    return ConfigResponse(
        supported_extensions=sorted(SUPPORTED_EXTENSIONS),
    )
