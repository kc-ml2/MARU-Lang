"""
Admin user management service
"""
from maru_lang.core.relation_db.models.auth import Team, User
from maru_lang.services.team import add_member_to_team


ADMIN_EMAIL = "admin@maru.local"
ADMIN_NAME = "Admin"
PUBLIC_TEAM_NAME = "public"


async def get_or_create_admin_user() -> User:
    """
    Admin 사용자를 가져오거나 없으면 생성합니다.
    CLI 명령어는 기본적으로 admin 사용자로 실행됩니다.

    Returns:
        Admin User 인스턴스
    """
    admin_user = await User.get_or_none(email=ADMIN_EMAIL)

    if admin_user is None:
        admin_user = await User.create(
            email=ADMIN_EMAIL,
            name=ADMIN_NAME,
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
    public_team = await Team.get_or_none(name=PUBLIC_TEAM_NAME)

    if public_team is None:
        admin_user = await get_or_create_admin_user()
        public_team = await Team.create(
            name=PUBLIC_TEAM_NAME,
            manager=admin_user,
            is_private=False,
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
