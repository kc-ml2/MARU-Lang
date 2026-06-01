"""Tests for create_conversation persistence (session, references, feedback)."""
import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import StateGraph, END

from maru_lang.core.relation_db.models.auth import Team
from maru_lang.core.relation_db.models.documents import Document, DocumentGroup
from maru_lang.core.relation_db.models.chat import Conversation, ConversationReference
from maru_lang.graph.rag.state import RagState
from maru_lang.api.ws.chat import stream_and_send
from maru_lang.services.chat import create_conversation
from maru_lang.services.session import create_session


class _FakeWebSocket:
    """Collects send_json payloads for assertions."""

    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, payload: dict):
        self.sent.append(payload)


@pytest.fixture()
async def document(user_alice) -> Document:
    team = await Team.create(name="DocTeam", manager=user_alice)
    group = await DocumentGroup.create(name="G", team=team)
    return await Document.create(id="doc-1", name="doc-1.pdf", group=group)


class TestCreateConversation:
    async def test_persists_turn_with_session_and_feedback(self, user_alice):
        session = await create_session(user_alice)
        conv = await create_conversation(
            user=user_alice,
            session=session,
            question="q?",
            answer="a.",
            references=[],
            feedback_score=4,
            feedback_reason="clear",
        )
        stored = await Conversation.get(id=conv.id).prefetch_related("session")
        assert stored.question == "q?"
        assert stored.answer == "a."
        assert stored.feedback_score == 4
        assert stored.feedback_reason == "clear"
        assert (await stored.session).id == session.id

    async def test_stores_reference_with_real_score(self, user_alice, document):
        conv = await create_conversation(
            user=user_alice,
            session=None,
            question="q",
            answer="a",
            references=[{"document_id": "doc-1", "score": 0.87}],
        )
        refs = await ConversationReference.filter(conversation=conv).all()
        assert len(refs) == 1
        assert refs[0].score == pytest.approx(0.87)  # not hardcoded 0

    async def test_deduplicates_and_skips_missing_documents(self, user_alice, document):
        conv = await create_conversation(
            user=user_alice,
            session=None,
            question="q",
            answer="a",
            references=[
                {"document_id": "doc-1", "score": 0.5},
                {"document_id": "doc-1", "score": 0.9},   # duplicate -> skipped
                {"document_id": "ghost", "score": 0.3},   # missing doc -> skipped
                {"score": 0.1},                            # no document_id -> skipped
            ],
        )
        refs = await ConversationReference.filter(conversation=conv).all()
        assert len(refs) == 1
        assert refs[0].score == pytest.approx(0.5)


class TestStreamAndSendPersistence:
    async def test_completed_turn_is_persisted_via_stream_and_send(self, user_alice):
        """End-to-end: stream_and_send reads final graph state and persists the turn."""
        def agent(state: RagState) -> dict:
            return {
                "messages": [AIMessage(content="the answer")],
                "retrieved_documents": [{"document_id": "doc-1", "score": 0.7}],
            }

        session = await create_session(user_alice)

        async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            await saver.setup()
            g = StateGraph(RagState)
            g.add_node("agent", agent)
            g.set_entry_point("agent")
            g.add_edge("agent", END)
            graph = g.compile(checkpointer=saver)

            ws = _FakeWebSocket()
            config = {"configurable": {"thread_id": f"{session.id}:turn-1"}}
            interrupted = await stream_and_send(
                ws, "my question", [1], ["team"], graph, config,
                user=user_alice, session=session, question="my question",
            )

        assert interrupted is False
        assert {"type": "complete"} in ws.sent

        conv = await Conversation.get(question="my question").prefetch_related("session")
        assert conv.answer == "the answer"
        assert (await conv.session).id == session.id

    async def test_nothing_persisted_without_question(self, user_alice):
        """A resume with no pending question (defensive) must not create a row."""
        def agent(state: RagState) -> dict:
            return {"messages": [AIMessage(content="x")]}

        async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            await saver.setup()
            g = StateGraph(RagState)
            g.add_node("agent", agent)
            g.set_entry_point("agent")
            g.add_edge("agent", END)
            graph = g.compile(checkpointer=saver)

            ws = _FakeWebSocket()
            config = {"configurable": {"thread_id": "t-x"}}
            await stream_and_send(
                ws, "hi", [1], ["team"], graph, config,
                user=user_alice, session=None, question=None,
            )

        assert {"type": "complete"} in ws.sent
        assert await Conversation.all().count() == 0
