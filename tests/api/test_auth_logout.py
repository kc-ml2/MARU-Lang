"""Logout must actually invalidate the access token.

get_user verifies the access token against the stored UserToken (not just the
JWT signature/expiry), so logout's UserToken.revoked_at takes effect.
"""
import pytest
from httpx import AsyncClient
from fastapi import FastAPI

from maru_lang.core.relation_db.models.auth import User
from maru_lang.services.auth import generate_token


@pytest.fixture()
def app() -> FastAPI:
    from maru_lang.api.endpoints.auth import router
    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


class TestLogoutRevocation:

    async def test_logout_invalidates_access_token(
        self, client: AsyncClient, user_alice: User
    ):
        """After /auth/logout the previously-valid access token is rejected."""
        access_token, _ = await generate_token(user_alice.id, "dev-1")
        headers = {"Authorization": f"Bearer {access_token}"}

        # Valid before logout.
        assert (await client.get("/auth/verify", headers=headers)).status_code == 200

        # Logout revokes the device's tokens.
        resp = await client.post(
            "/auth/logout", json={"device_id": "dev-1"}, headers=headers
        )
        assert resp.status_code == 200

        # Same (still un-expired) JWT is now rejected because UserToken is revoked.
        resp = await client.get("/auth/verify", headers=headers)
        assert resp.status_code == 401
