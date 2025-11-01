"""
Admin user management service
"""
from maru_lang.core.relation_db.models.auth import User


ADMIN_EMAIL = "admin@maru.local"
ADMIN_NAME = "Admin"


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


async def ensure_admin_user() -> User:
    """
    Admin 사용자가 존재하는지 확인하고 반환합니다.
    DB 초기화 시 호출됩니다.

    Returns:
        Admin User 인스턴스
    """
    return await get_or_create_admin_user()
