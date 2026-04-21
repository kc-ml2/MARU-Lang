"""RAG graph integration tests — structure, execution, consistency."""
import asyncio

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from langchain_core.documents import Document
from langchain_core.messages import AIMessage
from maru_lang.constants import RAG_EVALUATE_MAX_RETRIES


def _make_mock_retriever(ainvoke_return=None):
    """Create a mock retriever that supports model_copy (used by retrieve_node)."""
    retriever = MagicMock()
    retriever.team_ids = []
    retriever.ainvoke = AsyncMock(return_value=ainvoke_return or [])

    def _model_copy(update=None):
        copy = MagicMock()
        copy.ainvoke = retriever.ainvoke
        if update:
            for k, v in update.items():
                setattr(copy, k, v)
        return copy
    retriever.model_copy = MagicMock(side_effect=_model_copy)
    return retriever


# ─── Graph Structure ─────────────────────────────────────────


class TestRagGraphStructure:
    def test_graph_compiles_with_all_nodes(self):
        from maru_lang.graph.rag.graph import create_rag_graph

        mock_retriever = _make_mock_retriever()
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="test"))

        graph = create_rag_graph(mock_retriever, mock_llm)
        node_names = list(graph.get_graph().nodes.keys())

        for expected in ["intent", "keywords", "retrieve", "evaluate", "rerank", "format"]:
            assert expected in node_names, f"Missing node: {expected}"

    def test_graph_has_correct_edges(self):
        from maru_lang.graph.rag.graph import create_rag_graph

        mock_retriever = _make_mock_retriever()
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="test"))

        graph = create_rag_graph(mock_retriever, mock_llm)
        edges_str = str(graph.get_graph().edges)

        assert "intent" in edges_str
        assert "keywords" in edges_str
        assert "retrieve" in edges_str
        assert "evaluate" in edges_str
        assert "rerank" in edges_str
        assert "format" in edges_str


# ─── Graph Execution ─────────────────────────────────────────


class TestRagGraphExecution:
    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="rewritten query keywords"))
        return llm

    @pytest.fixture
    def good_docs(self):
        return [
            Document(page_content=f"content {i}", metadata={
                "document_id": f"d{i}", "document_name": f"doc{i}.pdf",
                "score": 0.8, "file_path": f"/path/{i}", "group_id": 1,
            })
            for i in range(3)
        ]

    @pytest.mark.asyncio
    async def test_retry_path_then_succeed(self, mock_llm):
        from maru_lang.graph.rag.graph import create_rag_graph

        good_docs = [
            Document(page_content=f"content {i}", metadata={
                "document_id": f"d{i}", "document_name": f"doc{i}.pdf",
                "score": 0.8, "file_path": f"/path/{i}", "group_id": 1,
            })
            for i in range(3)
        ]

        call_count = 0
        async def retriever_side_effect(query, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [Document(page_content="single", metadata={"score": 0.1})]
            return good_docs

        mock_retriever = _make_mock_retriever()
        mock_retriever.ainvoke = AsyncMock(side_effect=retriever_side_effect)

        graph = create_rag_graph(mock_retriever, mock_llm)

        result = await asyncio.wait_for(
            graph.ainvoke({
                "query": "test",
                "rewritten_query": "",
                "keywords": [],
                "documents": [],
                "result": "",
                "team_ids": [1],
                "retry_count": 0,
                "evaluation": "",
                "messages": [],
            }),
            timeout=5.0,
        )

        assert result["result"]
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_max_retry_forces_rerank(self, mock_llm):
        from maru_lang.graph.rag.graph import create_rag_graph

        mock_retriever = _make_mock_retriever()
        mock_retriever.ainvoke = AsyncMock(return_value=[
            Document(page_content="single", metadata={"score": 0.1}),
        ])

        graph = create_rag_graph(mock_retriever, mock_llm)

        result = await asyncio.wait_for(
            graph.ainvoke({
                "query": "test",
                "rewritten_query": "",
                "keywords": [],
                "documents": [],
                "result": "",
                "team_ids": [1],
                "retry_count": 0,
                "evaluation": "",
                "messages": [],
            }),
            timeout=10.0,
        )

        assert result["result"]
        assert any("FAIL" in m and f"{RAG_EVALUATE_MAX_RETRIES}/{RAG_EVALUATE_MAX_RETRIES}" in m for m in result["messages"])


# ─── evaluate_node + evaluate_route Consistency ──────────────


class TestEvaluateNodeRouteConsistency:
    """Verify evaluate_node sets marker and evaluate_route reads it correctly."""

    @pytest.mark.asyncio
    async def test_pass_marker_routes_to_rerank(self):
        from maru_lang.graph.rag.nodes.evaluate import make_evaluate_node, evaluate_route

        docs = [
            Document(page_content=f"c{i}", metadata={"score": 0.8})
            for i in range(3)
        ]
        state = {"documents": docs, "retry_count": 0, "rewritten_query": "", "query": "q"}

        node = make_evaluate_node(method="rule")
        node_result = await node(state)

        assert node_result["evaluation"] == "pass"

        merged_state = {**state, **node_result}
        route = evaluate_route(merged_state)
        assert route == "rerank"

    @pytest.mark.asyncio
    async def test_fail_marker_routes_to_retry(self):
        from maru_lang.graph.rag.nodes.evaluate import make_evaluate_node, evaluate_route

        docs = [Document(page_content="c0", metadata={"score": 0.1})]
        state = {"documents": docs, "retry_count": 0, "rewritten_query": "", "query": "q"}

        node = make_evaluate_node(method="rule")
        node_result = await node(state)

        assert node_result["evaluation"] == "fail"

        merged_state = {**state, **node_result}
        route = evaluate_route(merged_state)
        assert route == "retry"

    @pytest.mark.asyncio
    async def test_max_retry_marker_routes_to_rerank(self):
        from maru_lang.graph.rag.nodes.evaluate import make_evaluate_node, evaluate_route
        from maru_lang.constants import RAG_EVALUATE_MAX_RETRIES

        docs = [Document(page_content="c0", metadata={"score": 0.1})]
        state = {
            "documents": docs,
            "retry_count": RAG_EVALUATE_MAX_RETRIES,
            "rewritten_query": "",
            "query": "q",
        }

        node = make_evaluate_node(method="rule")
        node_result = await node(state)

        assert node_result["evaluation"] == "max_retry"

        merged_state = {**state, **node_result}
        route = evaluate_route(merged_state)
        assert route == "rerank"


# ─── LLM Verdict Parsing (strict) ────────────────────────────


class TestLLMEvaluateStrictVerdict:
    """`_llm_evaluate` must treat ambiguous LLM output as FAIL (retry),
    and only exact 'sufficient' as PASS — protects against verbose / negated verdicts."""

    async def _run(self, verdict_text: str):
        from maru_lang.graph.rag.nodes.evaluate import _llm_evaluate

        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content=verdict_text))
        state = {
            "query": "q",
            "rewritten_query": "",
            "documents": [Document(page_content="c", metadata={"score": 0.5})],
        }
        return await _llm_evaluate(state, llm)

    @pytest.mark.asyncio
    async def test_exact_sufficient_passes(self):
        assert await self._run("sufficient") is None

    @pytest.mark.asyncio
    async def test_sufficient_with_period_passes(self):
        assert await self._run("sufficient.") is None

    @pytest.mark.asyncio
    async def test_insufficient_fails(self):
        result = await self._run("insufficient")
        assert result is not None

    @pytest.mark.asyncio
    async def test_not_sufficient_fails(self):
        """Critical: 'not sufficient' must NOT be classified as pass."""
        result = await self._run("not sufficient")
        assert result is not None, "'not sufficient' must fail but got pass"

    @pytest.mark.asyncio
    async def test_verbose_answer_with_sufficient_fails(self):
        """LLM verbose response containing 'sufficient' word must not false-pass."""
        result = await self._run("The documents are sufficient to answer the query.")
        assert result is not None

    @pytest.mark.asyncio
    async def test_empty_response_fails(self):
        result = await self._run("")
        assert result is not None

    @pytest.mark.asyncio
    async def test_uppercase_sufficient_passes(self):
        """LLM might return uppercase; treat same as lowercase."""
        assert await self._run("SUFFICIENT") is None
