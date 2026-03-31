"""
익명 유저 활성화 테스트

익명 유저가 최초 로그인하면:
  - anonymous 롤이 제거된다
  - pending 멤버십이 member로 변경된다
"""
import pytest

from maru_lang.core.relation_db.models.auth import User, Team, TeamMember, UserRole
from maru_lang.enums.auth import UserRoleCode
from maru_lang.services.auth import create_or_get_user


class TestActivateAnonymousUser:
    """익명 유저가 최초 로그인(create_or_get_user) 시 활성화되는 흐름"""

    async def test_anonymous_role_removed_on_login(self):
        """로그인 시 anonymous 롤이 제거된다"""
        role = await UserRole.create(
            name=UserRoleCode.ANONYMOUS.value,
            description="초대로 생성된 미가입 유저",
        )
        user = await User.create(
            email="anon@example.com", name="Anon", role=role
        )

        returned_user = await create_or_get_user("anon@example.com")
        await returned_user.refresh_from_db()

        assert returned_user.id == user.id
        assert returned_user.role_id is None

    async def test_pending_memberships_become_member_on_login(self):
        """로그인 시 pending 멤버십이 member로 변경된다"""
        role = await UserRole.create(
            name=UserRoleCode.ANONYMOUS.value,
            description="초대로 생성된 미가입 유저",
        )
        manager = await User.create(email="manager@example.com", name="Manager")
        user = await User.create(
            email="anon@example.com", name="Anon", role=role
        )
        team = await Team.create(name="TestTeam", manager=manager)
        await TeamMember.create(user=user, team=team, role="pending")

        await create_or_get_user("anon@example.com")

        membership = await TeamMember.get(user=user, team=team)
        assert membership.role == "member"

    async def test_non_anonymous_user_unchanged(self):
        """anonymous가 아닌 유저는 로그인해도 변경되지 않는다"""
        editor_role = await UserRole.create(name="editor")
        user = await User.create(
            email="editor@example.com", name="Editor", role=editor_role
        )

        returned_user = await create_or_get_user("editor@example.com")
        await returned_user.refresh_from_db()

        assert returned_user.role_id == editor_role.id

    async def test_user_without_role_unchanged(self):
        """롤이 없는 일반 유저는 로그인해도 변경되지 않는다"""
        user = await User.create(email="normal@example.com", name="Normal")

        returned_user = await create_or_get_user("normal@example.com")
        await returned_user.refresh_from_db()

        assert returned_user.role_id is None
