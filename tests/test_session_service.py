"""Tests for the chat session service."""
from maru_lang.core.relation_db.models.chat import Session
from maru_lang.enums.chat import SessionStatus
from maru_lang.services.session import create_session, get_session_for_user


class TestCreateSession:
    async def test_creates_with_server_generated_id(self, user_alice):
        session = await create_session(user_alice, title="My chat")
        assert session.id and len(session.id) == 32  # uuid4().hex
        assert session.title == "My chat"
        assert session.status == SessionStatus.ACTIVE
        assert await Session.get(id=session.id)

    async def test_ids_are_unique(self, user_alice):
        a = await create_session(user_alice)
        b = await create_session(user_alice)
        assert a.id != b.id


class TestGetSessionForUser:
    async def test_returns_session_for_owner(self, user_alice):
        session = await create_session(user_alice)
        found = await get_session_for_user(session.id, user_alice)
        assert found is not None
        assert found.id == session.id

    async def test_none_for_other_user(self, user_alice, user_bob):
        session = await create_session(user_alice)
        assert await get_session_for_user(session.id, user_bob) is None

    async def test_none_for_unknown_id(self, user_alice):
        assert await get_session_for_user("does-not-exist", user_alice) is None

    async def test_none_for_deleted_session(self, user_alice):
        session = await create_session(user_alice)
        session.status = SessionStatus.DELETED
        await session.save()
        assert await get_session_for_user(session.id, user_alice) is None
