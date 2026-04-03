"""Internal endpoints for CLI integration (localhost only)."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from maru_lang.constants import CLI_DEVICE_ID, LOCALHOST_HOSTS
from maru_lang.core.llm import _get_llm_manager
from maru_lang.core.relation_db.models.auth import UserRole
from maru_lang.enums.auth import UserRoleCode
from maru_lang.services.admin import get_or_create_admin_user
from maru_lang.services.auth import generate_chat_token, generate_token
from maru_lang.services.team import add_member_to_team, get_or_create_team

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
    """Issue chat + access tokens for CLI usage. Localhost only."""
    client_host = request.client.host if request.client else None
    if client_host not in LOCALHOST_HOSTS:
        raise HTTPException(status_code=403, detail="Localhost access only")

    admin_user = await get_or_create_admin_user()

    # Ensure admin has ADMIN role (required for API endpoints)
    if not admin_user.role_id:
        role, _ = await UserRole.get_or_create(
            name=UserRoleCode.ADMIN.value,
            defaults={"description": "Administrator"},
        )
        admin_user.role = role
        await admin_user.save()

    # Ensure admin is a member of each requested team
    team_info = []
    for team_name in body.teams:
        team, _ = await get_or_create_team(name=team_name, manager=admin_user)
        await add_member_to_team(team, admin_user, role="admin")
        team_info.append({"id": team.id, "name": team.name})

    chat_token = await generate_chat_token(admin_user.id)
    access_token, _ = await generate_token(admin_user.id, CLI_DEVICE_ID)

    return CliTokenResponse(
        chat_token=chat_token,
        access_token=access_token,
        user_id=admin_user.id,
        teams=team_info,
    )


@router.get("/llms")
async def list_llms(request: Request):
    """List available LLM models. Localhost only."""
    client_host = request.client.host if request.client else None
    if client_host not in LOCALHOST_HOSTS:
        raise HTTPException(status_code=403, detail="Localhost access only")

    manager = _get_llm_manager()
    return {"llms": manager.list_clients()}
