"""Internal endpoints for CLI integration (localhost only)."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from maru_lang.constants import LOCALHOST_HOSTS
from maru_lang.core.llm import _get_llm_manager
from maru_lang.services.cli import issue_cli_tokens

router = APIRouter(
    prefix="/internal",
    tags=["Internal"],
)


class CliTokenRequest(BaseModel):
    teams: list[str] = []


class CliTokenResponse(BaseModel):
    chat_token: str
    access_token: str
    user_id: int
    teams: list[dict]


@router.post("/cli-token", response_model=CliTokenResponse)
async def get_cli_token(request: Request, body: CliTokenRequest):
    """Issue chat + access tokens for CLI usage. Localhost only.

    Joins existing teams only; an unknown team name returns 404 with the list
    of existing teams (team creation goes through the Teams API, not the CLI).
    """
    client_host = request.client.host if request.client else None
    if client_host not in LOCALHOST_HOSTS:
        raise HTTPException(status_code=403, detail="Localhost access only")

    try:
        return CliTokenResponse(**await issue_cli_tokens(body.teams))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/llms")
async def list_llms(request: Request):
    """List available LLM models. Localhost only."""
    client_host = request.client.host if request.client else None
    if client_host not in LOCALHOST_HOSTS:
        raise HTTPException(status_code=403, detail="Localhost access only")

    manager = _get_llm_manager()
    return {"llms": manager.list_clients()}
