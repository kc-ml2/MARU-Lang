"""Shared team authorization rules for application services and transports."""
from maru_lang.core.relation_db.models.auth import TeamMember, User
from maru_lang.enums import TeamRole


async def require_team_member(team_id: int, user: User) -> TeamMember:
    """Return the membership required for a team-scoped operation."""
    membership = await TeamMember.get_or_none(team_id=team_id, user_id=user.id)
    if membership is None:
        raise PermissionError("해당 팀의 멤버가 아닙니다")
    return membership


async def require_team_admin(team_id: int, user: User) -> TeamMember:
    """Return the admin membership required for a team mutation."""
    membership = await require_team_member(team_id, user)
    if membership.role != TeamRole.ADMIN:
        raise PermissionError("admin 권한이 필요합니다")
    return membership
