"""Tests for conversation persistence: create_conversation, context_builder, summarize."""
import pytest

from maru_lang.core.relation_db.models.auth import Team
from maru_lang.core.relation_db.models.documents import Document, DocumentGroup
from maru_lang.core.relation_db.models.chat import Conversation, ConversationReference, Session
from maru_lang.services.chat import create_conversation
from maru_lang.services.session import create_session


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


class TestContextBuilder:
    async def test_builds_memory_from_session(self, user_alice):
        from maru_lang.graph.rag.nodes.context import make_context_builder_node

        session = await create_session(user_alice)
        session.summary = "이전 대화 요약본"
        await session.save()
        await create_conversation(
            user=user_alice, session=session,
            question="작년 매출은?", answer="100억", references=[],
        )

        out = await make_context_builder_node()({"session_id": session.id})
        assert "이전 대화 요약본" in out["memory_context"]
        assert "작년 매출은?" in out["memory_context"]

    async def test_empty_when_no_session_id(self):
        from maru_lang.graph.rag.nodes.context import make_context_builder_node
        out = await make_context_builder_node()({})
        assert out["memory_context"] == ""

    async def test_includes_user_memory(self, user_alice):
        from maru_lang.enums.chat import UserMemoryKind
        from maru_lang.services.memory import upsert_user_memory
        from maru_lang.graph.rag.nodes.context import make_context_builder_node

        await upsert_user_memory(user_alice.id, UserMemoryKind.FACT, "김지훈", key="name")
        await upsert_user_memory(user_alice.id, UserMemoryKind.PREFERENCE, "짧은 말투 선호")
        out = await make_context_builder_node()({"user_id": user_alice.id})
        assert "김지훈" in out["memory_context"]
        assert "짧은 말투" in out["memory_context"]


class TestUserMemoryService:
    async def test_fact_upsert_by_key(self, user_alice):
        from maru_lang.enums.chat import UserMemoryKind
        from maru_lang.services.memory import upsert_user_memory, list_user_memories

        await upsert_user_memory(user_alice.id, UserMemoryKind.FACT, "김지훈", key="name")
        await upsert_user_memory(user_alice.id, UserMemoryKind.FACT, "김철수", key="name")
        names = [m for m in await list_user_memories(user_alice.id) if m.key == "name"]
        assert len(names) == 1 and names[0].content == "김철수"

    async def test_preference_dedup(self, user_alice):
        from maru_lang.enums.chat import UserMemoryKind
        from maru_lang.services.memory import upsert_user_memory, list_user_memories

        await upsert_user_memory(user_alice.id, UserMemoryKind.PREFERENCE, "짧은 말투")
        await upsert_user_memory(user_alice.id, UserMemoryKind.PREFERENCE, "짧은 말투")
        assert len(await list_user_memories(user_alice.id)) == 1


class TestMemoryExtractor:
    async def test_extracts_and_upserts(self, user_alice):
        from unittest.mock import MagicMock, AsyncMock
        from langchain_core.language_models import BaseChatModel
        from langchain_core.messages import AIMessage, HumanMessage
        from maru_lang.graph.rag.nodes.memory import make_memory_extractor_node
        from maru_lang.services.memory import list_user_memories

        model = MagicMock(spec=BaseChatModel)
        model.ainvoke = AsyncMock(return_value=AIMessage(
            content='[{"kind":"fact","key":"name","content":"김지훈"},{"kind":"preference","content":"짧은 말투"}]'
        ))
        node = make_memory_extractor_node(model)
        await node({"user_id": user_alice.id, "messages": [HumanMessage(content="내 이름은 김지훈이야")]})

        mems = await list_user_memories(user_alice.id)
        assert len(mems) == 2
        assert any(m.key == "name" and m.content == "김지훈" for m in mems)

    async def test_noop_without_user_id(self):
        from unittest.mock import MagicMock, AsyncMock
        from langchain_core.language_models import BaseChatModel
        from maru_lang.graph.rag.nodes.memory import make_memory_extractor_node

        model = MagicMock(spec=BaseChatModel)
        model.ainvoke = AsyncMock()
        node = make_memory_extractor_node(model)
        out = await node({"messages": []})
        assert out == {}
        model.ainvoke.assert_not_called()  # 게이팅: LLM 호출 없음


def _direct_graph(answers):
    """create_rag_graph(mock) — route=DIRECT 경로로 mock 답변을 순서대로 반환."""
    from unittest.mock import patch, MagicMock, AsyncMock
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage

    model = MagicMock(spec=BaseChatModel)
    model.ainvoke = AsyncMock(side_effect=[AIMessage(content=a) for a in answers])
    with patch("maru_lang.graph.rag.graph.build_retriever", return_value=MagicMock()), \
         patch("maru_lang.graph.rag.graph.build_compressor", return_value=None):
        from maru_lang.graph.rag.graph import create_rag_graph
        return create_rag_graph(model=model)


class TestSummarizePersistence:
    async def test_graph_persists_conversation_and_session_summary(self, user_alice):
        """summarize 종착 노드가 Conversation 생성 + Session.summary 갱신."""
        from langchain_core.messages import HumanMessage

        session = await create_session(user_alice)
        # route=DIRECT → generate → summarize(turn, session 요약)
        graph = _direct_graph(["DIRECT", "안녕하세요", "인사 턴요약", "세션 누적요약"])

        await graph.ainvoke(
            {"messages": [HumanMessage(content="안녕")], "team_ids": [1], "team_names": ["t"],
             "session_id": session.id, "user_id": user_alice.id},
            config={"configurable": {"thread_id": "persist-1"}},
        )

        conv = await Conversation.get(session=session)
        assert conv.question == "안녕"
        assert conv.answer == "안녕하세요"
        assert conv.summary == "인사 턴요약"
        assert (await Session.get(id=session.id)).summary == "세션 누적요약"

    async def test_no_persist_without_user_and_session(self, user_alice):
        """게이팅: session_id/user_id 없으면 저장하지 않는다."""
        from langchain_core.messages import HumanMessage

        graph = _direct_graph(["DIRECT", "답변"])  # summarize는 게이팅으로 LLM 미호출
        await graph.ainvoke(
            {"messages": [HumanMessage(content="안녕")], "team_ids": [1], "team_names": ["t"]},
            config={"configurable": {"thread_id": "persist-2"}},
        )
        assert await Conversation.all().count() == 0
