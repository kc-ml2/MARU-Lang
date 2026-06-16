"""
본인 프로필(표시명/닉네임) 조회·변경 API 테스트.

  GET   /auth/me  — 내 프로필 조회
  PATCH /auth/me  — 내 표시명(닉네임) 변경 (본인만)
"""
import pytest
from httpx import AsyncClient
from fastapi import FastAPI

from maru_lang.core.relation_db.models.auth import User
from tests.conftest import auth_header


@pytest.fixture()
def app() -> FastAPI:
    from maru_lang.api.endpoints.auth import router
    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


class TestMeProfile:
    async def test_get_me(self, client: AsyncClient, user_alice: User):
        """내 프로필 조회."""
        resp = await client.get("/auth/me", headers=await auth_header(user_alice.id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == user_alice.id
        assert data["email"] == "alice@example.com"
        assert data["name"] == "Alice"

    async def test_update_my_nickname(self, client: AsyncClient, user_alice: User):
        """본인 표시명을 변경하면 전역 User.name이 바뀐다."""
        resp = await client.patch(
            "/auth/me", json={"name": "Alice2"},
            headers=await auth_header(user_alice.id),
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Alice2"

        alice = await User.get(id=user_alice.id)
        assert alice.name == "Alice2"

    async def test_update_does_not_affect_other_user(
        self, client: AsyncClient, user_alice: User, user_bob: User,
    ):
        """본인 변경이 다른 사용자 이름에 영향을 주지 않는다."""
        await client.patch(
            "/auth/me", json={"name": "Renamed"},
            headers=await auth_header(user_alice.id),
        )
        bob = await User.get(id=user_bob.id)
        assert bob.name == "Bob"

    async def test_empty_name_rejected(self, client: AsyncClient, user_alice: User):
        """빈 이름은 거부된다 (pydantic min_length → 422)."""
        resp = await client.patch(
            "/auth/me", json={"name": ""},
            headers=await auth_header(user_alice.id),
        )
        assert resp.status_code == 422

    async def test_whitespace_name_rejected(self, client: AsyncClient, user_alice: User):
        """공백만 있는 이름은 서비스에서 거부된다 (400)."""
        resp = await client.patch(
            "/auth/me", json={"name": "   "},
            headers=await auth_header(user_alice.id),
        )
        assert resp.status_code == 400

    async def test_requires_auth(self, client: AsyncClient):
        """미인증 요청은 401."""
        resp = await client.patch("/auth/me", json={"name": "X"})
        assert resp.status_code == 401
