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


def _make_rag_chain_graph(retriever, llm, method="rule", compressor=None):
    """Build a standalone RAG-pipeline graph from the node factories.

    Mirrors the retrieval portion of the merged graph (intent → keywords →
    retrieve → evaluate → rerank → format with the retry loop), without the
    agent, so the retry behaviour can be tested in isolation.
    """
    from langgraph.graph import StateGraph, END
    from maru_lang.graph.rag.state import RagState
    from maru_lang.graph.rag.nodes import (
        make_intent_node, make_keyword_node, make_retrieve_node,
        make_evaluate_node, evaluate_route, make_rerank_node, format_node,
    )

    g = StateGraph(RagState)
    g.add_node("intent", make_intent_node(llm))
    g.add_node("keywords", make_keyword_node(llm))
    g.add_node("retrieve", make_retrieve_node(retriever))
    g.add_node("evaluate", make_evaluate_node(method=method, llm=llm if method == "llm" else None))
    g.add_node("rerank", make_rerank_node(compressor))
    g.add_node("format", format_node)
    g.set_entry_point("intent")
    g.add_edge("intent", "keywords")
    g.add_edge("keywords", "retrieve")
    g.add_edge("retrieve", "evaluate")
    g.add_conditional_edges("evaluate", evaluate_route, {"rerank": "rerank", "retry": "keywords"})
    g.add_edge("rerank", "format")
    g.add_edge("format", END)
    return g.compile()


def _rag_seed(query="test", team_ids=(1,)):
    return {
        "query": query,
        "rewritten_query": "",
        "keywords": [],
        "documents": [],
        "result": "",
        "team_ids": list(team_ids),
        "retry_count": 0,
        "evaluation": "",
        "excluded_doc_ids": [],
        "rag_log": [],
    }


# ─── Graph Structure ─────────────────────────────────────────


class TestRagGraphStructure:
    @staticmethod
    def _build():
        from langchain_core.language_models import BaseChatModel
        from maru_lang.graph.rag.graph import create_rag_graph

        mock_model = MagicMock(spec=BaseChatModel)
        mock_model.bind_tools = MagicMock(return_value=mock_model)
        with patch("maru_lang.graph.rag.graph.build_retriever", return_value=_make_mock_retriever()), \
             patch("maru_lang.graph.rag.graph.build_compressor", return_value=None):
            return create_rag_graph(mock_model)

    def test_graph_compiles_with_all_nodes(self):
        node_names = list(self._build().get_graph().nodes.keys())
        # route(분류) + generate(답변) + RAG 파이프라인 노드
        for expected in ["intent", "keywords", "retrieve", "evaluate", "rerank", "format",
                         "route", "generate", "search_entry", "context_builder", "summarize", "memory_extractor"]:
            assert expected in node_names, f"Missing node: {expected}"

    def test_graph_has_correct_edges(self):
        edges_str = str(self._build().get_graph().edges)
        for expected in ["intent", "keywords", "retrieve", "evaluate", "rerank", "format",
                         "route", "generate", "search_entry", "context_builder", "summarize", "memory_extractor"]:
            assert expected in edges_str


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

        graph = _make_rag_chain_graph(mock_retriever, mock_llm)

        result = await asyncio.wait_for(
            graph.ainvoke(_rag_seed()),
            timeout=5.0,
        )

        assert result["result"]
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_max_retry_forces_rerank(self, mock_llm):
        mock_retriever = _make_mock_retriever()
        mock_retriever.ainvoke = AsyncMock(return_value=[
            Document(page_content="single", metadata={"score": 0.1}),
        ])

        graph = _make_rag_chain_graph(mock_retriever, mock_llm)

        result = await asyncio.wait_for(
            graph.ainvoke(_rag_seed()),
            timeout=10.0,
        )

        assert result["result"]
        assert any("FAIL" in m and f"{RAG_EVALUATE_MAX_RETRIES}/{RAG_EVALUATE_MAX_RETRIES}" in m for m in result["rag_log"])


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


# ─── Reranker: low-score filtering (issue #1) ───────────────


class TestRerankerMinScore:
    @staticmethod
    def _rerank(min_score, scores):
        from maru_lang.graph.rag.reranker.cross_encoder import CrossEncoderCompressor
        docs = [Document(page_content=f"doc{i}") for i in range(len(scores))]
        fake_model = MagicMock()
        fake_model.predict = MagicMock(return_value=scores)
        import threading
        with patch(
            "maru_lang.graph.rag.reranker.cross_encoder._get_or_load_model",
            return_value=fake_model,
        ), patch(
            "maru_lang.graph.rag.reranker.cross_encoder._get_inference_lock",
            return_value=threading.Lock(),
        ):
            compressor = CrossEncoderCompressor(min_score=min_score)
            return compressor.compress_documents(docs, "query")

    def test_low_scores_filtered(self):
        result = self._rerank(min_score=0.5, scores=[0.9, 0.1, 0.7])
        assert len(result) == 2
        assert all(d.metadata["reranker_score"] >= 0.5 for d in result)
        # 점수 내림차순 정렬 유지
        assert result[0].metadata["reranker_score"] >= result[1].metadata["reranker_score"]

    def test_none_keeps_all(self):
        result = self._rerank(min_score=None, scores=[0.9, 0.1, 0.7])
        assert len(result) == 3


# ─── Intent node: memory-aware query rewriting (issue #13) ───


class TestIntentNodeMemory:
    """Intent must use recent conversation context so follow-up questions
    (pronouns/ellipsis/one-word replies) become self-contained queries."""

    @staticmethod
    def _node(rewritten: str):
        from maru_lang.graph.rag.nodes import make_intent_node
        captured = {}
        llm = MagicMock()

        async def ainvoke(prompt):
            captured["prompt"] = prompt
            r = MagicMock()
            r.content = rewritten
            return r

        llm.ainvoke = ainvoke
        return make_intent_node(llm), captured

    @pytest.mark.asyncio
    async def test_followup_uses_memory_context(self):
        node, captured = self._node("졸업하려면 TEPS가 필요한가요?")
        out = await node({
            "query": "TEPS!",
            "memory_context": "Q: 졸업하려면 텝스 필요해?\nA: ...",
        })
        # Prior context AND the current message reach the rewrite prompt.
        assert "졸업하려면 텝스" in captured["prompt"]
        assert "TEPS!" in captured["prompt"]
        assert out["rewritten_query"] == "졸업하려면 TEPS가 필요한가요?"

    @pytest.mark.asyncio
    async def test_no_memory_falls_back_to_plain_query(self):
        node, captured = self._node("rewritten")
        await node({"query": "hello", "memory_context": ""})
        assert "Original query: hello" in captured["prompt"]

    @pytest.mark.asyncio
    async def test_llm_failure_keeps_original_query(self):
        from maru_lang.graph.rag.nodes import make_intent_node
        llm = MagicMock()
        llm.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
        node = make_intent_node(llm)
        out = await node({"query": "TEPS!", "memory_context": "ctx"})
        assert out["rewritten_query"] == "TEPS!"
