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
from maru_lang.graph.chat.graph import create_chat_graph, _build_retriever_and_compressor
from maru_lang.graph.rag.retriever import VectorRetriever

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
            retriever, compressor = _build_retriever_and_compressor(cfg)
            assert isinstance(retriever, VectorRetriever)

            from maru_lang.graph.rag.reranker import LLMReranker
            assert isinstance(compressor, LLMReranker)
            assert compressor.top_k == 5

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
        from unittest.mock import patch, MagicMock

        mock_embeddings = MagicMock()
        with patch("maru_lang.graph.rag.retriever.vector.get_embeddings", return_value=mock_embeddings):
            cfg = MaruConfig(
                retriever_top_k=10,
                embedding_model="custom/model",
                reranker_enabled=False,
            )
            retriever, compressor = _build_retriever_and_compressor(cfg)
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


# ─── New Unit Tests ──────────────────────────────────────────


class TestShouldContinue:
    def test_returns_tools_when_tool_calls_exist(self):
        from langchain_core.messages import AIMessage
        from langgraph.graph import END
        from maru_lang.graph.chat.graph import _should_continue

        msg = AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "1"}])
        state = {"messages": [msg], "team_ids": [], "team_names": []}
        assert _should_continue(state) == "tools"

    def test_returns_end_when_no_tool_calls(self):
        from langchain_core.messages import AIMessage
        from langgraph.graph import END
        from maru_lang.graph.chat.graph import _should_continue

        msg = AIMessage(content="answer")
        state = {"messages": [msg], "team_ids": [], "team_names": []}
        assert _should_continue(state) == END

    def test_returns_end_when_tool_calls_empty_list(self):
        from langchain_core.messages import AIMessage
        from langgraph.graph import END
        from maru_lang.graph.chat.graph import _should_continue

        msg = AIMessage(content="answer", tool_calls=[])
        state = {"messages": [msg], "team_ids": [], "team_names": []}
        assert _should_continue(state) == END


class TestMakeAgentNode:
    @pytest.mark.asyncio
    async def test_default_system_prompt_when_empty(self):
        from unittest.mock import AsyncMock, MagicMock
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        from langchain_core.language_models import BaseChatModel
        from maru_lang.graph.chat.nodes import make_agent_node
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
        from maru_lang.graph.chat.nodes import make_agent_node

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

class TestMakeToolsNode:
    @pytest.mark.asyncio
    async def test_extracts_retrieved_documents_from_tool_message(self):
        from unittest.mock import AsyncMock, patch, MagicMock
        from langchain_core.messages import ToolMessage, AIMessage
        from maru_lang.graph.chat.nodes import make_tools_node

        doc_json = '[{"doc_id": "1", "title": "test"}]'
        tool_content = f"some result <!-- retrieved_documents:{doc_json} -->"
        tool_msg = ToolMessage(content=tool_content, tool_call_id="call_1")

        mock_tool_node = MagicMock()
        mock_tool_node.ainvoke = AsyncMock(return_value={"messages": [tool_msg]})

        with patch("maru_lang.graph.chat.nodes.ToolNode", return_value=mock_tool_node):
            node = make_tools_node([])
            state = {
                "messages": [AIMessage(content="", tool_calls=[{"name": "knowledge_search", "args": {}, "id": "call_1"}])],
                "team_ids": [],
                "team_names": [],
            }
            result = await node(state)

        assert "retrieved_documents" in result
        assert result["retrieved_documents"][0]["doc_id"] == "1"

    @pytest.mark.asyncio
    async def test_strips_metadata_trailer_from_content(self):
        from unittest.mock import AsyncMock, patch, MagicMock
        from langchain_core.messages import ToolMessage, AIMessage
        from maru_lang.graph.chat.nodes import make_tools_node

        doc_json = '[{"doc_id": "2"}]'
        tool_content = f"visible result <!-- retrieved_documents:{doc_json} -->"
        tool_msg = ToolMessage(content=tool_content, tool_call_id="call_2")

        mock_tool_node = MagicMock()
        mock_tool_node.ainvoke = AsyncMock(return_value={"messages": [tool_msg]})

        with patch("maru_lang.graph.chat.nodes.ToolNode", return_value=mock_tool_node):
            node = make_tools_node([])
            state = {
                "messages": [AIMessage(content="", tool_calls=[{"name": "knowledge_search", "args": {}, "id": "call_2"}])],
                "team_ids": [],
                "team_names": [],
            }
            result = await node(state)

        returned_msg = result["messages"][0]
        assert "<!-- retrieved_documents:" not in returned_msg.content
        assert "visible result" in returned_msg.content

    @pytest.mark.asyncio
    async def test_graceful_on_invalid_json(self):
        from unittest.mock import AsyncMock, patch, MagicMock
        from langchain_core.messages import ToolMessage, AIMessage
        from maru_lang.graph.chat.nodes import make_tools_node

        tool_content = "result <!-- retrieved_documents:not_json -->"
        tool_msg = ToolMessage(content=tool_content, tool_call_id="call_3")

        mock_tool_node = MagicMock()
        mock_tool_node.ainvoke = AsyncMock(return_value={"messages": [tool_msg]})

        with patch("maru_lang.graph.chat.nodes.ToolNode", return_value=mock_tool_node):
            node = make_tools_node([])
            state = {
                "messages": [AIMessage(content="", tool_calls=[{"name": "knowledge_search", "args": {}, "id": "call_3"}])],
                "team_ids": [],
                "team_names": [],
            }
            # Should not raise
            result = await node(state)

        assert "retrieved_documents" not in result

class TestCreateChatGraphAutoModel:
    def test_raises_when_no_model_available(self):
        from unittest.mock import patch
        from maru_lang.graph.chat.graph import create_chat_graph

        with patch("maru_lang.graph.chat.graph.get_model_with_fallbacks", return_value=None):
            with pytest.raises(RuntimeError, match="No LLM model available"):
                create_chat_graph()
