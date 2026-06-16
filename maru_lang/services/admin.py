"""
Admin user management service
"""
from maru_lang.core.relation_db.models.auth import Team, User
from maru_lang.services.team import add_member_to_team
from maru_lang.constants import ADMIN_EMAIL, ADMIN_NAME, PUBLIC_TEAM_NAME


async def get_or_create_admin_user() -> User:
    """
    Admin 사용자를 가져오거나 없으면 생성합니다.
    CLI 명령어는 기본적으로 admin 사용자로 실행됩니다.

    tortoise의 get_or_create를 사용해 동시 기동(서버 + 워커 N개)이 같은
    순간에 호출해도 레이스 없이 한 명만 생성됩니다 (IntegrityError 시 재조회).

    Returns:
        Admin User 인스턴스
    """
    admin_user, _ = await User.get_or_create(
        email=ADMIN_EMAIL,
        defaults={"name": ADMIN_NAME},
    )
    return admin_user


async def get_or_create_public_team() -> Team:
    """
    Public 팀을 가져오거나 없으면 생성합니다.
    모든 사용자가 기본적으로 속하는 팀입니다.
    Manager는 항상 admin입니다.

    Returns:
        Public Team 인스턴스
    """
    admin_user = await get_or_create_admin_user()
    public_team, _ = await Team.get_or_create(
        name=PUBLIC_TEAM_NAME,
        defaults={"manager": admin_user, "is_private": False},
    )
    return public_team


async def ensure_admin_user() -> User:
    """
    Admin 사용자와 public 팀이 존재하는지 확인합니다.
    DB 초기화 시 호출됩니다.

    Returns:
        Admin User 인스턴스
    """
    admin_user = await get_or_create_admin_user()
    public_team = await get_or_create_public_team()
    await add_member_to_team(public_team, admin_user, role="admin")
    return admin_user
