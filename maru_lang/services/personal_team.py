"""Personal workspace lifecycle."""
from pathlib import Path

from tortoise.transactions import in_transaction

from maru_lang.core.relation_db.models.auth import Team, TeamMember, User
from maru_lang.enums import TeamRole
from maru_lang.services.storage import ensure_default_source_storage


async def ensure_personal_team(root: Path, user: User) -> Team:
    """Return the user's private workspace, creating it once when absent."""
    team = await Team.get_or_none(manager=user, is_personal=True)
    if team is not None:
        await ensure_default_source_storage(root, team)
        await TeamMember.get_or_create(
            user=user,
            team=team,
            defaults={"role": TeamRole.ADMIN},
        )
        return team

    async with in_transaction():
        # Concurrent verification requests may race; lock the user row and check
        # again before creating the one allowed personal workspace.
        locked_user = await User.select_for_update().get(id=user.id)
        team = await Team.get_or_none(manager=locked_user, is_personal=True)
        if team is None:
            team = await Team.create(
                name=f"{locked_user.name or locked_user.email}의 공간",
                manager=locked_user,
                is_personal=True,
            )
            await TeamMember.create(
                user=locked_user, team=team, role=TeamRole.ADMIN
            )

    await ensure_default_source_storage(root, team)
    return team
