import pytest
from fastapi import FastAPI
from httpx import AsyncClient


@pytest.fixture()
def app() -> FastAPI:
    from maru_lang.api.endpoints.auth import router

    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


class TestAuthLogin:
    async def test_login_blocked_domain_returns_403(
        self, client: AsyncClient, monkeypatch
    ):
        from maru_lang.api.endpoints import auth as auth_module

        monkeypatch.setattr(
            auth_module.config.auth, "allowed_domains", ["kct.co.kr"]
        )

        resp = await client.post(
            "/auth/login",
            json={"email": "user@blocked.com"},
        )

        assert resp.status_code == 403
        assert "허용되지 않은 이메일 도메인" in resp.json()["detail"]

    async def test_login_allowed_domain_succeeds(
        self, client: AsyncClient, monkeypatch
    ):
        from maru_lang.api.endpoints import auth as auth_module

        monkeypatch.setattr(
            auth_module.config.auth, "allowed_domains", ["kct.co.kr"]
        )

        resp = await client.post(
            "/auth/login",
            json={"email": "user@kct.co.kr"},
        )

        assert resp.status_code == 200
        assert resp.json() == "user@kct.co.kr"

    async def test_login_multiple_at_rejected(
        self, client: AsyncClient, monkeypatch
    ):
        """"a@evil.com@kct.co.kr" must not bypass the allow-list (422 at schema)."""
        from maru_lang.api.endpoints import auth as auth_module

        monkeypatch.setattr(
            auth_module.config.auth, "allowed_domains", ["kct.co.kr"]
        )

        resp = await client.post(
            "/auth/login",
            json={"email": "attacker@evil.com@kct.co.kr"},
        )

        assert resp.status_code == 422
