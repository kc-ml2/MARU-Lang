"""Unified RAG + ReAct agent graph tests (unit, no API key needed).

  venv/bin/python -m pytest tests/test_chat.py -v

실제 LLM 호출이 필요한 시나리오는 `maru test`(tests/configs/test_sample_config_e2e.py
의 TestLLMSmoke)로 이전됨.
"""
import sys
import types
import pytest

# Bypass maru_lang.__init__ full app loading
if "maru_lang" not in sys.modules:
    _fake = types.ModuleType("maru_lang")
    _fake.__path__ = ["maru_lang"]
    sys.modules["maru_lang"] = _fake


from maru_lang.configs.models import MaruConfig, LLMConfig
from maru_lang.graph.rag.state import RagState
from maru_lang.graph.rag.graph import create_rag_graph
from maru_lang.graph.rag.retriever import VectorRetriever, build_retriever
from maru_lang.graph.rag.reranker import build_compressor

# ─── Unit Tests (no API key needed) ─────────────────────────


class TestState:
    def test_state_has_required_keys(self):
        keys = list(RagState.__annotations__.keys())
        assert "messages" in keys
        assert "team_ids" in keys
        assert "retrieved_documents" in keys
        # rag pipeline fields merged in
        assert "documents" in keys
        assert "rag_log" in keys  # renamed from the old rag `messages` progress log

    def test_state_messages_has_reducer(self):
        from typing import get_type_hints
        hints = get_type_hints(RagState, include_extras=True)
        assert hasattr(hints["messages"], "__metadata__")


class TestGraphCompilation:
    @staticmethod
    def _make_graph():
        from unittest.mock import MagicMock, patch
        from langchain_core.language_models import BaseChatModel

        mock_model = MagicMock(spec=BaseChatModel)
        mock_model.bind_tools = MagicMock(return_value=mock_model)

        # Avoid loading real embeddings/reranker when compiling.
        with patch("maru_lang.graph.rag.graph.build_retriever", return_value=MagicMock()), \
             patch("maru_lang.graph.rag.graph.build_compressor", return_value=None):
            return create_rag_graph(mock_model)

    def test_graph_compiles_with_mock_model(self):
        compiled = self._make_graph()
        nodes = list(compiled.get_graph().nodes.keys())
        # route(분류) + generate(답변) + RAG 파이프라인 노드
        assert "route" in nodes
        assert "generate" in nodes
        assert "search_entry" in nodes
        assert "intent" in nodes
        assert "evaluate" in nodes
        # ReAct/tool 잔재 없음
        assert "agent" not in nodes
        assert "search_result" not in nodes

    def test_graph_has_correct_edges(self):
        compiled = self._make_graph()
        edge_strs = str(compiled.get_graph().edges)
        assert "route" in edge_strs
        assert "generate" in edge_strs
        assert "search_entry" in edge_strs


class TestBuildRetriever:
    @pytest.fixture(autouse=True)
    def _mock_heavy_deps(self):
        """Mock get_vector_db and get_embeddings so VectorRetriever construction
        doesn't require real ChromaDB/HuggingFace downloads in unit tests."""
        from unittest.mock import patch, MagicMock
        mock_vdb = MagicMock()
        mock_emb = MagicMock()
        with patch("maru_lang.graph.rag.retriever.vector.get_vector_db", return_value=mock_vdb), \
             patch("maru_lang.graph.rag.retriever.vector.get_embeddings", return_value=mock_emb):
            yield

    def test_no_reranker_returns_vector_retriever(self):
        cfg = MaruConfig(reranker_enabled=False)
        assert isinstance(build_retriever(cfg), VectorRetriever)
        assert build_compressor(cfg) is None

    def test_cross_encoder_reranker(self):
        cfg = MaruConfig(
            reranker_enabled=True,
            reranker_type="cross_encoder",
            reranker_model="BAAI/bge-reranker-v2-m3",
            reranker_top_k=3,
        )
        compressor = build_compressor(cfg)

        from maru_lang.graph.rag.reranker import CrossEncoderCompressor
        assert isinstance(compressor, CrossEncoderCompressor)
        assert compressor.model_name == "BAAI/bge-reranker-v2-m3"
        assert compressor.top_k == 3

    def test_llm_reranker(self):
        from unittest.mock import patch, MagicMock
        from langchain_core.language_models import BaseChatModel

        mock_llm = MagicMock(spec=BaseChatModel)
        with patch("maru_lang.graph.rag.reranker.create_chat_model", return_value=mock_llm):
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
            compressor = build_compressor(cfg)

            from maru_lang.graph.rag.reranker import LLMReranker
            assert isinstance(compressor, LLMReranker)
            assert compressor.top_k == 5

    def test_llm_reranker_falls_back_to_first_llm(self):
        from unittest.mock import patch, MagicMock
        from langchain_core.language_models import BaseChatModel

        mock_llm = MagicMock(spec=BaseChatModel)
        with patch("maru_lang.graph.rag.reranker.create_chat_model", return_value=mock_llm):
            cfg = MaruConfig(
                reranker_enabled=True,
                reranker_type="llm",
                reranker_llm=None,
                llms=[
                    LLMConfig(name="fallback", provider="openai", model_name="gpt-4o-mini",
                              api_key="fake-key"),
                ],
            )
            assert build_compressor(cfg) is not None

    def test_llm_reranker_no_llms_raises(self):
        cfg = MaruConfig(
            reranker_enabled=True,
            reranker_type="llm",
            llms=[],
        )
        with pytest.raises(RuntimeError, match="LLM reranker requires"):
            build_compressor(cfg)

    def test_retriever_inherits_config_values(self):
        cfg = MaruConfig(
            retriever_top_k=10,
            embedding_model="custom/model",
            reranker_enabled=False,
        )
        retriever = build_retriever(cfg)
        assert isinstance(retriever, VectorRetriever)
        assert retriever.top_k == 10


# NOTE: 실제 LLM 호출이 필요한 chat integration 시나리오(simple query, multi-turn,
# feedback, direct answer)는 `maru test`로 실행되는 tests/configs/test_sample_config_e2e.py
# 의 TestLLMSmoke(llm_smoke 마커)로 이전됨.


# ─── New Unit Tests ──────────────────────────────────────────


class TestRouting:
    def test_route_decision_search(self):
        from maru_lang.graph.rag.nodes.route import route_decision
        assert route_decision({"route": "search"}) == "search_entry"

    def test_route_decision_direct(self):
        from maru_lang.graph.rag.nodes.route import route_decision
        assert route_decision({"route": "direct"}) == "generate"

    def test_feedback_route_on(self):
        from maru_lang.graph.rag.nodes.feedback import feedback_route
        assert feedback_route({"function": "feedback"}) == "score"

    def test_feedback_route_off(self):
        from maru_lang.graph.rag.nodes.feedback import feedback_route
        assert feedback_route({}) == "summarize"


class TestRouteNode:
    @pytest.mark.asyncio
    async def test_classifies_search_vs_direct(self):
        from unittest.mock import AsyncMock, MagicMock
        from langchain_core.messages import AIMessage, HumanMessage
        from langchain_core.language_models import BaseChatModel
        from maru_lang.graph.rag.nodes.route import make_route_node

        model = MagicMock(spec=BaseChatModel)
        model.ainvoke = AsyncMock(return_value=AIMessage(content="DIRECT"))
        node = make_route_node(model)
        out = await node({"messages": [HumanMessage(content="안녕")]})
        assert out["route"] == "direct"

        model.ainvoke = AsyncMock(return_value=AIMessage(content="SEARCH"))
        out = await node({"messages": [HumanMessage(content="우리 휴가 규정?")]})
        assert out["route"] == "search"


class TestGenerateNode:
    @pytest.mark.asyncio
    async def test_default_system_prompt_and_context_injection(self):
        from unittest.mock import AsyncMock, MagicMock
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        from langchain_core.language_models import BaseChatModel
        from maru_lang.graph.rag.nodes.generate import make_generate_node
        from maru_lang.constants import SYSTEM_PROMPT

        model = MagicMock(spec=BaseChatModel)
        model.ainvoke = AsyncMock(return_value=AIMessage(content="답변"))

        node = make_generate_node(model, "")
        # 검색 결과(result)가 있으면 컨텍스트 SystemMessage가 추가되어야 함
        await node({"messages": [HumanMessage(content="hi")], "result": "문서내용"})

        sent = model.ainvoke.call_args[0][0]
        sys_msgs = [m for m in sent if isinstance(m, SystemMessage)]
        assert sys_msgs[0].content == SYSTEM_PROMPT
        assert any("문서내용" in m.content for m in sys_msgs)  # context 주입

    @pytest.mark.asyncio
    async def test_no_context_when_no_result(self):
        from unittest.mock import AsyncMock, MagicMock
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        from langchain_core.language_models import BaseChatModel
        from maru_lang.graph.rag.nodes.generate import make_generate_node

        model = MagicMock(spec=BaseChatModel)
        model.ainvoke = AsyncMock(return_value=AIMessage(content="답변"))
        node = make_generate_node(model, "prompt")
        await node({"messages": [HumanMessage(content="hi")]})

        sent = model.ainvoke.call_args[0][0]
        sys_msgs = [m for m in sent if isinstance(m, SystemMessage)]
        assert len(sys_msgs) == 1  # 컨텍스트 없음 → 시스템 프롬프트 하나뿐


class TestSearchEntryNode:
    @pytest.mark.asyncio
    async def test_seeds_query_from_message_and_resets(self):
        from langchain_core.messages import HumanMessage
        from maru_lang.graph.rag.nodes.search import make_search_entry_node

        node = make_search_entry_node()
        state = {"messages": [HumanMessage(content="강남 스시 맛집?")], "team_ids": [1],
                 "retry_count": 2, "excluded_doc_ids": ["x"], "documents": ["stale"]}
        result = await node(state)

        assert result["query"] == "강남 스시 맛집?"
        assert result["retry_count"] == 0
        assert result["excluded_doc_ids"] == []
        assert result["documents"] == []


class TestFormatNode:
    @pytest.mark.asyncio
    async def test_sets_result_and_retrieved_documents(self):
        from langchain_core.documents import Document
        from maru_lang.graph.rag.nodes.format import format_node

        doc = Document(page_content="본문", metadata={"document_id": "d1", "score": 0.5})
        out = await format_node({"documents": [doc], "query": "q"})
        assert out["result"]
        assert out["retrieved_documents"][0]["document_id"] == "d1"
        assert out["retrieved_documents"][0]["score"] == 0.5

    @pytest.mark.asyncio
    async def test_empty_when_no_documents(self):
        from maru_lang.graph.rag.nodes.format import format_node
        out = await format_node({"documents": [], "query": "q"})
        assert out["retrieved_documents"] == []


class TestCreateRagGraphAutoModel:
    def test_raises_when_no_model_available(self):
        from unittest.mock import patch
        from maru_lang.graph.rag.graph import create_rag_graph

        with patch("maru_lang.graph.rag.graph.get_model_with_fallbacks", return_value=None):
            with pytest.raises(RuntimeError, match="No LLM model available"):
                create_rag_graph()
