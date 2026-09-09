"""Trusted operator provisioning (not a team-admin API)."""
from email_validator import validate_email, EmailNotValidError
from tortoise.transactions import in_transaction

from maru_lang.core.relation_db.models.auth import Team, TeamMember, User
from maru_lang.enums import TeamRole
from maru_lang.services.personal_team import ensure_personal_team
from maru_lang.services.storage import ensure_default_source_storage
from maru_lang.settings import Settings


def normalized_email(email: str, settings: Settings) -> str:
    try:
        email = validate_email(email, check_deliverability=False).normalized
    except EmailNotValidError as exc:
        raise ValueError(str(exc)) from exc
    if not settings.is_domain_allowed(email):
        raise ValueError("Email domain is not allowed")
    return email


async def add_user(settings: Settings, email: str, team_name: str, role: str):
    email = normalized_email(email, settings)
    team_name = team_name.strip()
    if not team_name or len(team_name) > 255 or team_name.startswith("personal-"):
        raise ValueError("Team name must be 1–255 characters and not start with personal-")
    role = TeamRole(role)
    async with in_transaction():
        team = await Team.get_or_none(name=team_name)
        if team is not None and team.is_personal:
            raise ValueError("Cannot add members to a personal team")
        if team is None and role != TeamRole.ADMIN:
            raise ValueError("A new team's first user must have role admin")
        user, user_created = await User.get_or_create(email=email)
        team_created = team is None
        if team is None:
            team = await Team.create(name=team_name, manager=user)
        member, member_created = await TeamMember.get_or_create(
            user=user, team=team, defaults={"role": role}
        )
        if member.role != role:
            raise ValueError("Existing membership has a different role; implicit role changes are refused")
    # Filesystem provisioning is idempotent, but not part of the DB transaction.
    await ensure_personal_team(settings.filesystem_root, user)
    await ensure_default_source_storage(settings.filesystem_root, team)
    return user, {
        "user_id": user.id, "email": user.email, "user_created": user_created,
        "team_id": team.id, "team": team.name, "team_created": team_created,
        "role": member.role, "member_created": member_created,
    }
