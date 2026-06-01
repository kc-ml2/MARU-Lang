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
from maru_lang.graph.rag.graph import create_rag_graph, _build_retriever_and_compressor
from maru_lang.graph.rag.retriever import VectorRetriever

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
        with patch(
            "maru_lang.graph.rag.graph._build_retriever_and_compressor",
            return_value=(MagicMock(), None),
        ):
            return create_rag_graph(mock_model)

    def test_graph_compiles_with_mock_model(self):
        compiled = self._make_graph()
        nodes = list(compiled.get_graph().nodes.keys())
        # agent + search plumbing + rag pipeline nodes all in one graph
        assert "agent" in nodes
        assert "search_entry" in nodes
        assert "search_result" in nodes
        assert "intent" in nodes
        assert "evaluate" in nodes
        # no separate ToolNode anymore
        assert "tools" not in nodes

    def test_graph_has_correct_edges(self):
        compiled = self._make_graph()
        edge_strs = str(compiled.get_graph().edges)
        assert "agent" in edge_strs
        assert "search_entry" in edge_strs
        assert "search_result" in edge_strs


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
        retriever, compressor = _build_retriever_and_compressor(cfg)
        assert isinstance(retriever, VectorRetriever)
        assert compressor is None

    def test_cross_encoder_reranker(self):
        cfg = MaruConfig(
            reranker_enabled=True,
            reranker_type="cross_encoder",
            reranker_model="BAAI/bge-reranker-v2-m3",
            reranker_top_k=3,
        )
        retriever, compressor = _build_retriever_and_compressor(cfg)
        assert isinstance(retriever, VectorRetriever)

        from maru_lang.graph.rag.reranker import CrossEncoderCompressor
        assert isinstance(compressor, CrossEncoderCompressor)
        assert compressor.model_name == "BAAI/bge-reranker-v2-m3"
        assert compressor.top_k == 3

    def test_llm_reranker(self):
        from unittest.mock import patch, MagicMock
        from langchain_core.language_models import BaseChatModel

        mock_llm = MagicMock(spec=BaseChatModel)
        with patch("maru_lang.graph.rag.graph.create_chat_model", return_value=mock_llm):
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
            retriever, compressor = _build_retriever_and_compressor(cfg)
            assert isinstance(retriever, VectorRetriever)

            from maru_lang.graph.rag.reranker import LLMReranker
            assert isinstance(compressor, LLMReranker)
            assert compressor.top_k == 5

    def test_llm_reranker_falls_back_to_first_llm(self):
        from unittest.mock import patch, MagicMock
        from langchain_core.language_models import BaseChatModel

        mock_llm = MagicMock(spec=BaseChatModel)
        with patch("maru_lang.graph.rag.graph.create_chat_model", return_value=mock_llm):
            cfg = MaruConfig(
                reranker_enabled=True,
                reranker_type="llm",
                reranker_llm=None,
                llms=[
                    LLMConfig(name="fallback", provider="openai", model_name="gpt-4o-mini",
                              api_key="fake-key"),
                ],
            )
            retriever, compressor = _build_retriever_and_compressor(cfg)
            assert compressor is not None

    def test_llm_reranker_no_llms_raises(self):
        cfg = MaruConfig(
            reranker_enabled=True,
            reranker_type="llm",
            llms=[],
        )
        with pytest.raises(RuntimeError, match="LLM reranker requires"):
            _build_retriever_and_compressor(cfg)

    def test_retriever_inherits_config_values(self):
        cfg = MaruConfig(
            retriever_top_k=10,
            embedding_model="custom/model",
            reranker_enabled=False,
        )
        retriever, compressor = _build_retriever_and_compressor(cfg)
        assert isinstance(retriever, VectorRetriever)
        assert retriever.top_k == 10


# NOTE: 실제 LLM 호출이 필요한 chat integration 시나리오(simple query, multi-turn,
# feedback, direct answer)는 `maru test`로 실행되는 tests/configs/test_sample_config_e2e.py
# 의 TestLLMSmoke(llm_smoke 마커)로 이전됨.


# ─── New Unit Tests ──────────────────────────────────────────


class TestShouldContinue:
    def test_returns_search_entry_when_tool_calls_exist(self):
        from langchain_core.messages import AIMessage
        from maru_lang.graph.rag.graph import _should_continue

        msg = AIMessage(content="", tool_calls=[{"name": "knowledge_search", "args": {"query": "q"}, "id": "1"}])
        state = {"messages": [msg], "team_ids": [], "team_names": []}
        assert _should_continue(state) == "search_entry"

    def test_returns_end_when_no_tool_calls(self):
        from langchain_core.messages import AIMessage
        from langgraph.graph import END
        from maru_lang.graph.rag.graph import _should_continue

        msg = AIMessage(content="answer")
        state = {"messages": [msg], "team_ids": [], "team_names": []}
        assert _should_continue(state) == END

    def test_returns_score_when_feedback_mode(self):
        from langchain_core.messages import AIMessage
        from maru_lang.graph.rag.graph import _should_continue

        msg = AIMessage(content="answer")
        state = {"messages": [msg], "team_ids": [], "function": "feedback"}
        assert _should_continue(state) == "score"


class TestMakeAgentNode:
    @pytest.mark.asyncio
    async def test_default_system_prompt_when_empty(self):
        from unittest.mock import AsyncMock, MagicMock
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        from langchain_core.language_models import BaseChatModel
        from maru_lang.graph.rag.nodes.agent import make_agent_node
        from maru_lang.constants import SYSTEM_PROMPT

        mock_model = MagicMock(spec=BaseChatModel)
        mock_model.ainvoke = AsyncMock(return_value=AIMessage(content="response"))

        node = make_agent_node(mock_model, "")
        state = {
            "messages": [HumanMessage(content="hello")],
            "team_ids": [],
            "team_names": [],
        }
        await node(state)

        call_args = mock_model.ainvoke.call_args[0][0]
        assert isinstance(call_args[0], SystemMessage)
        assert call_args[0].content == SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_existing_system_message_not_duplicated(self):
        from unittest.mock import AsyncMock, MagicMock
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        from langchain_core.language_models import BaseChatModel
        from maru_lang.graph.rag.nodes.agent import make_agent_node

        mock_model = MagicMock(spec=BaseChatModel)
        mock_model.ainvoke = AsyncMock(return_value=AIMessage(content="response"))

        node = make_agent_node(mock_model, "custom prompt")
        state = {
            "messages": [
                SystemMessage(content="existing system"),
                HumanMessage(content="hello"),
            ],
            "team_ids": [],
            "team_names": [],
        }
        await node(state)

        call_args = mock_model.ainvoke.call_args[0][0]
        system_messages = [m for m in call_args if isinstance(m, SystemMessage)]
        assert len(system_messages) == 1
        assert system_messages[0].content == "existing system"


class TestSearchEntryNode:
    @pytest.mark.asyncio
    async def test_extracts_query_and_id_and_resets(self):
        from langchain_core.messages import AIMessage
        from maru_lang.graph.rag.nodes.search import make_search_entry_node

        node = make_search_entry_node()
        msg = AIMessage(
            content="",
            tool_calls=[{"name": "knowledge_search", "args": {"query": "물어볼것"}, "id": "call_9"}],
        )
        # Carry stale rag fields to confirm reset
        state = {"messages": [msg], "team_ids": [1], "retry_count": 2,
                 "excluded_doc_ids": ["x"], "rag_log": ["old"]}
        result = await node(state)

        assert result["query"] == "물어볼것"
        assert result["tool_call_id"] == "call_9"
        assert result["retry_count"] == 0
        assert result["excluded_doc_ids"] == []
        assert result["rag_log"] == []
        assert result["documents"] == []


class TestSearchResultNode:
    @pytest.mark.asyncio
    async def test_builds_tool_message_and_sets_documents(self):
        from langchain_core.documents import Document
        from langchain_core.messages import ToolMessage
        from maru_lang.graph.rag.nodes.search import make_search_result_node

        node = make_search_result_node()
        doc = Document(page_content="본문", metadata={"document_id": "d1", "score": 0.5})
        state = {"result": "formatted", "tool_call_id": "call_7", "documents": [doc]}
        result = await node(state)

        msg = result["messages"][0]
        assert isinstance(msg, ToolMessage)
        assert msg.tool_call_id == "call_7"
        assert msg.content == "formatted"
        assert result["retrieved_documents"][0]["document_id"] == "d1"
        assert result["retrieved_documents"][0]["score"] == 0.5


class TestCreateRagGraphAutoModel:
    def test_raises_when_no_model_available(self):
        from unittest.mock import patch
        from maru_lang.graph.rag.graph import create_rag_graph

        with patch("maru_lang.graph.rag.graph.get_model_with_fallbacks", return_value=None):
            with pytest.raises(RuntimeError, match="No LLM model available"):
                create_rag_graph()
