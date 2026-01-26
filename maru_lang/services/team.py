"""
Team management service
"""
from maru_lang.core.relation_db.models.auth import Team, TeamMember, User


async def list_teams_by_user(user: User) -> list[Team]:
    """
    User가 속한 Team 목록 조회

    Args:
        user: User 인스턴스

    Returns:
        list[Team]: User가 속한 Team 목록
    """
    teams = await Team.filter(members__user=user).all()
    return teams


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


async def add_member_to_team(
    team: Team,
    user: User,
    role: str = "member",
) -> tuple[TeamMember, bool]:
    """
    User를 Team에 가입시킴

    Args:
        team: Team 인스턴스
        user: 가입시킬 User 인스턴스
        role: 역할 (기본값: "member")

    Returns:
        tuple[TeamMember, bool]: (TeamMember 인스턴스, 신규 생성 여부)
    """
    membership, created = await TeamMember.get_or_create(
        user=user,
        team=team,
        defaults={"role": role},
    )
    return membership, created
