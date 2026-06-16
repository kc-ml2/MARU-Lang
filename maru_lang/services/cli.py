"""CLI/internal-flow services — localhost token issuance for the `maru` CLI."""
from maru_lang.constants import CLI_DEVICE_ID
from maru_lang.core.relation_db.models.auth import Team, UserRole
from maru_lang.enums.auth import UserRoleCode
from maru_lang.services.admin import get_or_create_admin_user, get_or_create_public_team
from maru_lang.services.auth import generate_chat_token, generate_token
from maru_lang.services.team import add_member_to_team


async def issue_cli_tokens(team_names: list[str]) -> dict:
    """Issue chat + access tokens for the CLI's admin user.

    Joins existing teams only — it never creates them. Team lookup is by exact
    name string, so silently creating on a typo/case mismatch used to leave the
    user in a brand-new empty team; now unknown names fail with the list of
    existing teams. Teams are created via the Teams API (POST /teams). The one
    exception is the system 'public' team, which is bootstrapped here (same as
    orm_context does for CLI/worker) so a fresh DB still serves the default run.

    Raises:
        ValueError: If any requested team does not exist.
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

    # System bootstrap: the default team always exists.
    await get_or_create_public_team()

    # Resolve all requested teams first — fail before touching memberships.
    teams: list[Team] = []
    missing: list[str] = []
    for team_name in team_names:
        team = await Team.get_or_none(name=team_name)
        if team is None:
            missing.append(team_name)
        else:
            teams.append(team)
    if missing:
        existing = sorted(await Team.all().values_list("name", flat=True))
        raise ValueError(
            f"Team(s) not found: {', '.join(missing)}. "
            f"Existing teams: {', '.join(existing) or '(none)'}. "
            "Teams are created via the Teams API, not the CLI."
        )

    team_info = []
    for team in teams:
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
