"""LangGraph ReAct 그래프 E2E 테스트

실행 방법:
  # OpenAI
  OPENAI_API_KEY=sk-... venv/bin/python -m pytest tests/test_graph.py -v

  # Anthropic
  ANTHROPIC_API_KEY=sk-... venv/bin/python -m pytest tests/test_graph.py -v -k anthropic
"""
import os
import sys
import types
import pytest

# maru_lang.__init__의 전체 앱 로딩 우회
if "maru_lang" not in sys.modules:
    _fake = types.ModuleType("maru_lang")
    _fake.__path__ = ["maru_lang"]
    sys.modules["maru_lang"] = _fake


from maru_lang.graph.state import ChatState
from maru_lang.graph.graph import create_graph, ALL_TOOLS
from maru_lang.graph.tools.dummy_search import knowledge_search
from maru_lang.graph.tools.memory import (
    memory_read,
    memory_write,
    clear_memory_store,
    get_memory_store,
)

# ─── Unit Tests (API 키 불필요) ───────────────────────────────


class TestState:
    def test_state_has_required_keys(self):
        keys = list(ChatState.__annotations__.keys())
        assert "messages" in keys
        assert "team_ids" in keys
        assert "retrieved_documents" in keys

    def test_state_messages_has_reducer(self):
        # messages 필드에 add_messages reducer가 적용되어 있는지 확인
        from typing import get_type_hints
        hints = get_type_hints(ChatState, include_extras=True)
        assert hasattr(hints["messages"], "__metadata__")


class TestTools:
    def test_knowledge_search_returns_results(self):
        result = knowledge_search.invoke({"query": "RAG", "search_method": "hybrid"})
        assert "RAG" in result or "doc_" in result

    def test_knowledge_search_fallback(self):
        result = knowledge_search.invoke({"query": "없는키워드xyz", "search_method": "vector"})
        assert "doc_001" in result  # fallback으로 기본 문서 반환

    def test_memory_write_and_read(self):
        clear_memory_store()
        write_result = memory_write.invoke({
            "content": "사용자는 Python을 선호합니다",
            "memory_type": "preference",
        })
        assert "저장" in write_result

        read_result = memory_read.invoke({"query": "Python"})
        assert "Python" in read_result
        assert "preference" in read_result

    def test_memory_read_empty(self):
        clear_memory_store()
        result = memory_read.invoke({"query": "아무거나"})
        assert "저장된 기억이 없습니다" in result

    def test_memory_read_no_match(self):
        clear_memory_store()
        memory_write.invoke({"content": "테스트 메모리", "memory_type": "fact"})
        result = memory_read.invoke({"query": "없는내용xyz"})
        assert "찾지 못했습니다" in result


class TestGraphCompilation:
    def test_graph_compiles_with_mock_model(self):
        from unittest.mock import MagicMock
        from langchain_core.language_models import BaseChatModel

        mock_model = MagicMock(spec=BaseChatModel)
        mock_model.bind_tools = MagicMock(return_value=mock_model)

        compiled = create_graph(mock_model)
        nodes = list(compiled.get_graph().nodes.keys())
        assert "agent" in nodes
        assert "tools" in nodes

    def test_graph_has_correct_edges(self):
        from unittest.mock import MagicMock
        from langchain_core.language_models import BaseChatModel

        mock_model = MagicMock(spec=BaseChatModel)
        mock_model.bind_tools = MagicMock(return_value=mock_model)

        compiled = create_graph(mock_model)
        graph_repr = compiled.get_graph()

        # agent → tools, agent → __end__, tools → agent 엣지 확인
        edge_strs = str(graph_repr.edges)
        assert "agent" in edge_strs
        assert "tools" in edge_strs


# ─── Integration Tests (API 키 필요) ─────────────────────────


def _get_openai_model():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model="gpt-4o-mini", temperature=0)


def _get_anthropic_model():
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(model="claude-sonnet-4-20250514", temperature=0)


def _make_input(question: str) -> dict:
    from langchain_core.messages import HumanMessage
    return {
        "messages": [HumanMessage(content=question)],
        "team_ids": [1],
        "team_names": ["test-team"],
        "accessible_groups": ["general", "technical"],
        "retrieved_documents": [],
    }


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
class TestOpenAIIntegration:

    @pytest.fixture(autouse=True)
    def setup(self):
        clear_memory_store()
        self.graph = create_graph(_get_openai_model())
        self.config = {"configurable": {"thread_id": "test-openai-1"}}

    @pytest.mark.asyncio
    async def test_simple_search_query(self):
        result = await self.graph.ainvoke(
            _make_input("MARU 프로젝트가 뭐야?"),
            config=self.config,
        )
        last_msg = result["messages"][-1].content
        assert len(last_msg) > 10
        print(f"\n[OpenAI] Response: {last_msg[:300]}")

    @pytest.mark.asyncio
    async def test_memory_roundtrip(self):
        # 1차: 선호도 저장
        result1 = await self.graph.ainvoke(
            _make_input("나는 기술 문서를 선호해. 기억해줘."),
            config=self.config,
        )
        print(f"\n[OpenAI] Memory write: {result1['messages'][-1].content[:200]}")

        # 2차: 기억 확인
        result2 = await self.graph.ainvoke(
            _make_input("내가 어떤 문서를 선호한다고 했지?"),
            config=self.config,
        )
        last_msg = result2["messages"][-1].content
        print(f"[OpenAI] Memory read: {last_msg[:200]}")

    @pytest.mark.asyncio
    async def test_multi_turn_conversation(self):
        config = {"configurable": {"thread_id": "test-openai-multi"}}

        r1 = await self.graph.ainvoke(
            _make_input("RAG 파이프라인 구조를 알려줘"),
            config=config,
        )
        print(f"\n[OpenAI] Turn 1: {r1['messages'][-1].content[:200]}")

        # 같은 thread_id로 후속 질문 → 대화 맥락 유지
        r2 = await self.graph.ainvoke(
            _make_input("더 자세히 설명해줘"),
            config=config,
        )
        print(f"[OpenAI] Turn 2: {r2['messages'][-1].content[:200]}")


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set")
class TestAnthropicIntegration:

    @pytest.fixture(autouse=True)
    def setup(self):
        clear_memory_store()
        self.graph = create_graph(_get_anthropic_model())
        self.config = {"configurable": {"thread_id": "test-anthropic-1"}}

    @pytest.mark.asyncio
    async def test_simple_search_query(self):
        result = await self.graph.ainvoke(
            _make_input("MARU 프로젝트가 뭐야?"),
            config=self.config,
        )
        last_msg = result["messages"][-1].content
        assert len(last_msg) > 10
        print(f"\n[Anthropic] Response: {last_msg[:300]}")
