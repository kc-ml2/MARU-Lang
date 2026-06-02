"""Memory API: list / delete / clear the caller's persistent memories."""
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from maru_lang.enums.chat import UserMemoryKind
from maru_lang.services.memory import upsert_user_memory, list_user_memories
from tests.conftest import auth_header


@pytest.fixture()
def app() -> FastAPI:
    from maru_lang.api.endpoints.memory import router as memory_router
    test_app = FastAPI()
    test_app.include_router(memory_router)
    return test_app


@pytest.fixture()
async def client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestListMemories:
    async def test_lists_user_memories(self, client, user_alice):
        await upsert_user_memory(user_alice.id, UserMemoryKind.FACT, "김지훈", key="name")
        resp = await client.get("/memories", headers=auth_header(user_alice.id))
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["content"] == "김지훈"
        assert body[0]["kind"] == UserMemoryKind.FACT

    async def test_requires_auth(self, client):
        assert (await client.get("/memories")).status_code == 401


class TestDeleteMemory:
    async def test_delete_one(self, client, user_alice):
        m = await upsert_user_memory(user_alice.id, UserMemoryKind.PREFERENCE, "짧은 말투")
        resp = await client.delete(f"/memories/{m.id}", headers=auth_header(user_alice.id))
        assert resp.status_code == 204
        assert await list_user_memories(user_alice.id) == []

    async def test_delete_missing_returns_404(self, client, user_alice):
        resp = await client.delete("/memories/9999", headers=auth_header(user_alice.id))
        assert resp.status_code == 404

    async def test_cannot_delete_other_users_memory(self, client, user_alice, user_bob):
        m = await upsert_user_memory(user_bob.id, UserMemoryKind.FACT, "비밀", key="x")
        resp = await client.delete(f"/memories/{m.id}", headers=auth_header(user_alice.id))
        assert resp.status_code == 404  # not owner → not found
        assert len(await list_user_memories(user_bob.id)) == 1  # untouched


class TestClearMemories:
    async def test_clear_all(self, client, user_alice):
        await upsert_user_memory(user_alice.id, UserMemoryKind.FACT, "a", key="k1")
        await upsert_user_memory(user_alice.id, UserMemoryKind.FACT, "b", key="k2")
        resp = await client.delete("/memories", headers=auth_header(user_alice.id))
        assert resp.status_code == 204
        assert await list_user_memories(user_alice.id) == []
