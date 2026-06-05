"""CLI/internal-flow services — localhost token issuance for the `maru` CLI."""
from maru_lang.constants import CLI_DEVICE_ID
from maru_lang.core.relation_db.models.auth import UserRole
from maru_lang.enums.auth import UserRoleCode
from maru_lang.services.admin import get_or_create_admin_user
from maru_lang.services.auth import generate_chat_token, generate_token
from maru_lang.services.team import add_member_to_team, get_or_create_team


async def issue_cli_tokens(team_names: list[str]) -> dict:
    """Issue chat + access tokens for the CLI's admin user.

    Ensures the admin user exists with the ADMIN role, makes it a member of each
    requested team (creating teams as needed), and returns fresh tokens plus the
    resolved team list. Caller (the /internal endpoint) handles localhost gating.
    """
    admin_user = await get_or_create_admin_user()

    # Ensure admin has the ADMIN role (required for API endpoints).
    if not admin_user.role_id:
        role, _ = await UserRole.get_or_create(
            name=UserRoleCode.ADMIN.value,
            defaults={"description": "Administrator"},
        )
        admin_user.role = role
        await admin_user.save()

    # Ensure admin is a member of each requested team.
    team_info = []
    for team_name in team_names:
        team, _ = await get_or_create_team(name=team_name, manager=admin_user)
        await add_member_to_team(team, admin_user, role="admin")
        team_info.append({"id": team.id, "name": team.name})

    chat_token = await generate_chat_token(admin_user.id)
    access_token, _ = await generate_token(admin_user.id, CLI_DEVICE_ID)

    return {
        "chat_token": chat_token,
        "access_token": access_token,
        "user_id": admin_user.id,
        "teams": team_info,
    }
