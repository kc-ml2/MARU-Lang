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
