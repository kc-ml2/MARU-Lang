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


class TestSessionIdleWindow:
    """GET /sessions/last 동작: 7일 넘게 쉰 세션은 재개하지 않고 새로 만든다."""

    async def test_recent_session_is_resumed(self, user_alice):
        from maru_lang.services.session import get_or_create_last_session
        s = await create_session(user_alice)
        resumed = await get_or_create_last_session(user_alice)
        assert resumed.id == s.id

    async def test_stale_session_starts_a_new_one(self, user_alice):
        from datetime import datetime, timedelta, timezone
        from maru_lang.services.session import get_or_create_last_session

        s = await create_session(user_alice)
        # 8일 전 사용으로 위장 (queryset update는 auto_now를 덮지 않음)
        stale = datetime.now(timezone.utc) - timedelta(days=8)
        await Session.filter(id=s.id).update(updated_at=stale)

        fresh = await get_or_create_last_session(user_alice)
        assert fresh.id != s.id              # 새 세션 시작
        assert await Session.get(id=s.id)    # 옛 세션은 히스토리에 보존

    async def test_window_boundary_uses_max_idle_days(self, user_alice):
        from maru_lang.services.session import get_last_session
        await create_session(user_alice)
        # max_idle_days=0 → 방금 만든 세션도 창 밖 → None
        assert await get_last_session(user_alice, max_idle_days=0) is None
