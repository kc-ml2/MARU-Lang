"""Sessions API 통합 테스트.

엔드포인트:
  POST /sessions       — 새 세션 생성
  GET  /sessions/last  — 마지막 세션 조회 (없으면 생성)
"""
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from maru_lang.core.relation_db.models.chat import Session
from maru_lang.enums.chat import SessionStatus
from maru_lang.services.session import create_session
from tests.conftest import auth_header


@pytest.fixture()
def app() -> FastAPI:
    """Test app with only the sessions router."""
    from maru_lang.api.endpoints.session import router as session_router

    test_app = FastAPI()
    test_app.include_router(session_router)
    return test_app


@pytest.fixture()
async def client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestCreateSession:
    async def test_creates_session(self, client, user_alice):
        resp = await client.post("/sessions", json={"title": "hello"}, headers=auth_header(user_alice.id))
        assert resp.status_code == 201
        body = resp.json()
        assert len(body["id"]) == 32
        assert body["title"] == "hello"
        assert body["status"] == SessionStatus.ACTIVE
        assert await Session.get(id=body["id"])

    async def test_title_optional(self, client, user_alice):
        resp = await client.post("/sessions", json={}, headers=auth_header(user_alice.id))
        assert resp.status_code == 201
        assert resp.json()["title"] is None

    async def test_requires_auth(self, client):
        assert (await client.post("/sessions", json={})).status_code == 401


class TestGetLastSession:
    async def test_creates_when_none_exists(self, client, user_alice):
        assert await Session.filter(user=user_alice).count() == 0
        resp = await client.get("/sessions/last", headers=auth_header(user_alice.id))
        assert resp.status_code == 200
        sid = resp.json()["id"]
        assert await Session.filter(user=user_alice).count() == 1
        assert await Session.get(id=sid)

    async def test_returns_most_recent(self, client, user_alice):
        first = await create_session(user_alice)
        last = await create_session(user_alice)  # newer updated_at
        resp = await client.get("/sessions/last", headers=auth_header(user_alice.id))
        assert resp.status_code == 200
        assert resp.json()["id"] == last.id

    async def test_ignores_other_users_sessions(self, client, user_alice, user_bob):
        await create_session(user_bob)
        resp = await client.get("/sessions/last", headers=auth_header(user_alice.id))
        assert resp.status_code == 200
        sid = resp.json()["id"]
        assert (await Session.get(id=sid).prefetch_related("user")).user_id == user_alice.id

    async def test_skips_deleted_and_creates_new(self, client, user_alice):
        deleted = await create_session(user_alice)
        deleted.status = SessionStatus.DELETED
        await deleted.save()
        resp = await client.get("/sessions/last", headers=auth_header(user_alice.id))
        assert resp.status_code == 200
        assert resp.json()["id"] != deleted.id
