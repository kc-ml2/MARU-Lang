"""Auto-created domain team is administered by the system admin.

On first login the domain team is created automatically; the system admin
(admin@maru.local) joins as admin while the logging-in user joins as a plain
member, so the first random logger does not become the org team's admin.
"""
from unittest.mock import patch, AsyncMock

import pytest
from httpx import AsyncClient
from fastapi import FastAPI

from maru_lang.constants import ADMIN_EMAIL
from maru_lang.core.relation_db.models.auth import User, Team, TeamMember
from maru_lang.services.admin import get_or_create_public_team


@pytest.fixture()
def app() -> FastAPI:
    from maru_lang.api.endpoints.auth import router
    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


async def _login(client: AsyncClient, email: str, device_id: str = "d1"):
    """Drive the OTP verify flow (code verification mocked) for `email`."""
    with patch(
        "maru_lang.api.endpoints.auth.verify_email_code",
        new=AsyncMock(return_value=True),
    ):
        return await client.post(
            "/auth/verify/code",
            json={"email": email, "code": "000000", "device_id": device_id},
        )


class TestDomainTeamAdmin:

    async def test_first_login_domain_team_admin_is_system_admin(
        self, client: AsyncClient
    ):
        """Auto-created domain team: system admin is admin, user is member."""
        # Ensure the system admin + public team exist (login flow relies on them).
        await get_or_create_public_team()

        with patch(
            "maru_lang.api.endpoints.auth.verify_email_code",
            new=AsyncMock(return_value=True),
        ):
            resp = await client.post(
                "/auth/verify/code",
                json={"email": "newuser@acme.com", "code": "000000", "device_id": "d1"},
            )
        assert resp.status_code == 200

        team = await Team.get(name="acme")
        admin_user = await User.get(email=ADMIN_EMAIL)
        new_user = await User.get(email="newuser@acme.com")

        admin_membership = await TeamMember.get(team=team, user=admin_user)
        user_membership = await TeamMember.get(team=team, user=new_user)

        assert admin_membership.role == "admin"
        assert user_membership.role == "member"

    async def test_domain_team_manager_is_system_admin(self, client: AsyncClient):
        """Team.manager must be the system admin, not the first logging-in user.

        manager is an ownership label + delete guard; the first random logger
        should not own (and thus pin against deletion) the org team.
        """
        await get_or_create_public_team()
        resp = await _login(client, "first@acme.com")
        assert resp.status_code == 200

        team = await Team.get(name="acme")
        admin_user = await User.get(email=ADMIN_EMAIL)
        assert team.manager_id == admin_user.id


class TestDomainTeamCollision:
    """첫 라벨만 같은 다른 도메인이 한 팀으로 병합되지 않아야 한다 (#23)."""

    async def test_same_prefix_different_domain_is_isolated(
        self, client: AsyncClient
    ):
        """acme.com 팀이 있어도 acme.co.kr 은 별도 팀으로 격리된다."""
        await get_or_create_public_team()
        assert (await _login(client, "kim@acme.com")).status_code == 200
        assert (await _login(client, "kim@acme.co.kr")).status_code == 200

        acme = await Team.get(name="acme")
        cokr = await Team.get(name="acme.co.kr")  # 격리된 전체 도메인 팀

        com_user = await User.get(email="kim@acme.com")
        cokr_user = await User.get(email="kim@acme.co.kr")

        # acme.co.kr 유저는 자기 팀에만 속하고, acme 팀엔 들어가지 않는다.
        assert await TeamMember.get_or_none(team=cokr, user=cokr_user) is not None
        assert await TeamMember.get_or_none(team=acme, user=cokr_user) is None
        assert await TeamMember.get_or_none(team=acme, user=com_user) is not None

    async def test_same_domain_second_user_joins_existing_team(
        self, client: AsyncClient
    ):
        """같은 도메인 두 번째 유저는 기존 팀에 합류 — 불필요한 분리 없음."""
        await get_or_create_public_team()
        assert (await _login(client, "alice@acme.com")).status_code == 200
        assert (await _login(client, "bob@acme.com")).status_code == 200

        # acme.com 으로 만들어진 별도 팀이 생기지 않아야 한다.
        assert await Team.get_or_none(name="acme.com") is None
        acme = await Team.get(name="acme")
        bob = await User.get(email="bob@acme.com")
        assert await TeamMember.get_or_none(team=acme, user=bob) is not None
