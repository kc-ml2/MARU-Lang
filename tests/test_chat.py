"""LangGraph ReAct chat graph tests

Run:
  # Unit tests (no API key needed)
  venv/bin/python -m pytest tests/test_chat.py -v

  # Integration (OpenAI)
  OPENAI_API_KEY=sk-... venv/bin/python -m pytest tests/test_chat.py -v -k integration

  # Integration (Anthropic)
  ANTHROPIC_API_KEY=sk-... venv/bin/python -m pytest tests/test_chat.py -v -k anthropic
"""
import os
import sys
import types
import pytest

# Bypass maru_lang.__init__ full app loading
if "maru_lang" not in sys.modules:
    _fake = types.ModuleType("maru_lang")
    _fake.__path__ = ["maru_lang"]
    sys.modules["maru_lang"] = _fake


from maru_lang.configs.models import MaruConfig, LLMConfig
from maru_lang.graph.chat.state import ChatState
from maru_lang.graph.chat.graph import create_chat_graph, _build_retriever
from maru_lang.graph.chat.retriever import VectorRetriever, CompressedRetriever

# ─── Unit Tests (no API key needed) ─────────────────────────


class TestState:
    def test_state_has_required_keys(self):
        keys = list(ChatState.__annotations__.keys())
        assert "messages" in keys
        assert "team_ids" in keys
        assert "retrieved_documents" in keys

    def test_state_messages_has_reducer(self):
        from typing import get_type_hints
        hints = get_type_hints(ChatState, include_extras=True)
        assert hasattr(hints["messages"], "__metadata__")


class TestGraphCompilation:
    @staticmethod
    def _make_graph():
        from unittest.mock import MagicMock
        from langchain_core.language_models import BaseChatModel
        from langchain_core.tools import tool

        mock_model = MagicMock(spec=BaseChatModel)
        mock_model.bind_tools = MagicMock(return_value=mock_model)

        @tool
        def dummy_tool(query: str) -> str:
            """Dummy tool for testing."""
            return "ok"

        return create_chat_graph(mock_model, tools=[dummy_tool])

    def test_graph_compiles_with_mock_model(self):
        compiled = self._make_graph()
        nodes = list(compiled.get_graph().nodes.keys())
        assert "agent" in nodes
        assert "tools" in nodes

    def test_graph_has_correct_edges(self):
        compiled = self._make_graph()
        edge_strs = str(compiled.get_graph().edges)
        assert "agent" in edge_strs
        assert "tools" in edge_strs


class TestBuildRetriever:
    def test_no_reranker_returns_vector_retriever(self):
        cfg = MaruConfig(reranker_enabled=False)
        retriever = _build_retriever(cfg)
        assert isinstance(retriever, VectorRetriever)

    def test_cross_encoder_reranker_returns_compressed(self):
        cfg = MaruConfig(
            reranker_enabled=True,
            reranker_type="cross_encoder",
            reranker_model="BAAI/bge-reranker-v2-m3",
            reranker_top_k=3,
        )
        retriever = _build_retriever(cfg)
        assert isinstance(retriever, CompressedRetriever)
        assert isinstance(retriever.base_retriever, VectorRetriever)

        from maru_lang.graph.chat.reranker import CrossEncoderCompressor
        assert isinstance(retriever.compressor, CrossEncoderCompressor)
        assert retriever.compressor.model_name == "BAAI/bge-reranker-v2-m3"
        assert retriever.compressor.top_k == 3

    def test_llm_reranker_returns_compressed(self):
        from unittest.mock import patch, MagicMock
        from langchain_core.language_models import BaseChatModel

        mock_llm = MagicMock(spec=BaseChatModel)
        with patch("maru_lang.graph.chat.graph.create_chat_model", return_value=mock_llm):
            cfg = MaruConfig(
                reranker_enabled=True,
                reranker_type="llm",
                reranker_llm="test-llm",
                reranker_top_k=5,
                llms=[
                    LLMConfig(name="test-llm", provider="openai", model_name="gpt-4o-mini",
                              api_key="fake-key"),
                ],
            )
            retriever = _build_retriever(cfg)
            assert isinstance(retriever, CompressedRetriever)

            from maru_lang.graph.chat.reranker import LLMReranker
            assert isinstance(retriever.compressor, LLMReranker)
            assert retriever.compressor.top_k == 5

    def test_llm_reranker_falls_back_to_first_llm(self):
        from unittest.mock import patch, MagicMock
        from langchain_core.language_models import BaseChatModel

        mock_llm = MagicMock(spec=BaseChatModel)
        with patch("maru_lang.graph.chat.graph.create_chat_model", return_value=mock_llm):
            cfg = MaruConfig(
                reranker_enabled=True,
                reranker_type="llm",
                reranker_llm=None,
                llms=[
                    LLMConfig(name="fallback", provider="openai", model_name="gpt-4o-mini",
                              api_key="fake-key"),
                ],
            )
            retriever = _build_retriever(cfg)
            assert isinstance(retriever, CompressedRetriever)

    def test_llm_reranker_no_llms_raises(self):
        cfg = MaruConfig(
            reranker_enabled=True,
            reranker_type="llm",
            llms=[],
        )
        with pytest.raises(RuntimeError, match="LLM reranker requires"):
            _build_retriever(cfg)

    def test_retriever_inherits_config_values(self):
        from unittest.mock import patch, MagicMock

        mock_embeddings = MagicMock()
        with patch("maru_lang.graph.chat.retriever.vector.get_embeddings", return_value=mock_embeddings):
            cfg = MaruConfig(
                retriever_top_k=10,
                embedding_model="custom/model",
                reranker_enabled=False,
            )
            retriever = _build_retriever(cfg)
            assert isinstance(retriever, VectorRetriever)
            assert retriever.top_k == 10


# ─── Integration Tests (API key required) ───────────────────


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
        self.graph = create_chat_graph(_get_openai_model())
        self.config = {"configurable": {"thread_id": "test-openai-1"}}

    @pytest.mark.asyncio
    async def test_simple_search_query(self):
        result = await self.graph.ainvoke(
            _make_input("MARU 프로젝트가 뭐야?"),
            config=self.config,
        )
        last_msg = result["messages"][-1].content
        assert len(last_msg) > 10

    @pytest.mark.asyncio
    async def test_multi_turn_conversation(self):
        config = {"configurable": {"thread_id": "test-openai-multi"}}

        await self.graph.ainvoke(
            _make_input("RAG 파이프라인 구조를 알려줘"),
            config=config,
        )
        r2 = await self.graph.ainvoke(
            _make_input("더 자세히 설명해줘"),
            config=config,
        )
        assert len(r2["messages"][-1].content) > 10


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set")
class TestAnthropicIntegration:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.graph = create_chat_graph(_get_anthropic_model())
        self.config = {"configurable": {"thread_id": "test-anthropic-1"}}

    @pytest.mark.asyncio
    async def test_simple_search_query(self):
        result = await self.graph.ainvoke(
            _make_input("MARU 프로젝트가 뭐야?"),
            config=self.config,
        )
        last_msg = result["messages"][-1].content
        assert len(last_msg) > 10
