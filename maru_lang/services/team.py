"""
Team management service
"""
from maru_lang.core.relation_db.models.auth import Team, User


async def get_or_create_team(
    name: str,
    manager: User,
    is_private: bool = False,
) -> tuple[Team, bool]:
    """
    Team을 조회하거나 생성

    Args:
        name: Team 이름
        manager: Team 관리자 User
        is_private: 비공개 여부

    Returns:
        tuple[Team, bool]: (Team 인스턴스, 신규 생성 여부)
    """
    team = await Team.get_or_none(name=name)
    if team:
        return team, False

    team = await Team.create(
        name=name,
        manager=manager,
        is_private=is_private,
    )
    return team, True
