"""실제 LLM 호출 E2E 스모크 — mock 없음.

`maru test`가 만든 임시 config(MARU_TEST_CONFIG_DIR)로 선택한 provider/모델에서
전체 파이프라인(실제 임베딩→ChromaDB→검색→reranker→병합 그래프 agent→RAG→응답)과
피드백 interrupt/resume 흐름을 검증한다 (TestLLMSmoke, llm_smoke 마커).

실행: `maru test`  (= pytest ... -m "integration and llm_smoke", MARU_TEST_CONFIG_DIR 설정)
MARU_TEST_CONFIG_DIR가 없으면 전부 skip되므로 CI의 `pytest -m integration`에서 안전하다.

참고: sample_config/*.yaml 자체의 유효성(파싱/구성)은 키 없는 유닛 테스트
`tests/configs/test_models.py::test_sample_config_is_valid`가 검증한다.
"""
import asyncio
import os
from pathlib import Path

import pytest

import maru_lang.configs.manager as cfg_mod
import maru_lang.core.llm as llm_mod
from maru_lang.configs.manager import reload_config
from maru_lang.core.llm.server_manager import LLMManager
from maru_lang.core.vector_db.chroma import ChromaVectorDB
from maru_lang.graph.ingest.embedder import get_embeddings
from maru_lang.graph.rag.retriever.vector import VectorRetriever

TEST_DOCS_DIR = Path(__file__).resolve().parent.parent / "test_documents"


def _load_test_docs() -> list[dict]:
    """tests/test_documents/*.txt 파일들을 읽어서 ChromaDB 인제스트 형식으로 변환."""
    docs = []
    for i, txt_path in enumerate(sorted(TEST_DOCS_DIR.glob("*.txt")), 1):
        content = txt_path.read_text(encoding="utf-8").strip()
        docs.append({
            "id": f"chunk-{i}",
            "content": content,
            "metadata": {
                "document_id": f"doc-{i}",
                "document_name": txt_path.name,
                "team_id": 1,
                "file_path": str(txt_path),
                "group_id": 1,
            },
        })
    return docs


@pytest.fixture(autouse=True)
def reset_singletons():
    """테스트 간 싱글턴 초기화."""
    cfg_mod._config = None
    llm_mod._llm_manager = None
    yield
    cfg_mod._config = None
    llm_mod._llm_manager = None


def _ingest_docs(vdb: ChromaVectorDB, embeddings, docs: list[dict]):
    """테스트 문서를 실제 임베딩 후 ChromaDB에 인제스트."""
    contents = [d["content"] for d in docs]
    vectors = embeddings.embed_documents(contents)
    vdb.add_documents(docs, vectors)


def _build_stack(cfg, tmp_path):
    """cfg로 실제 LLM + (테스트 문서 인제스트된) retriever + compressor 생성."""
    from maru_lang.core.llm.client import create_chat_model
    from maru_lang.graph.rag.reranker import CrossEncoderCompressor, LLMReranker

    manager = LLMManager(cfg.llms)
    enabled = [llm for llm in cfg.llms if llm.enabled]
    assert len(manager.clients) == len(enabled)
    llm = manager.get_model()

    embeddings = get_embeddings(
        model_name=cfg.embedding_model,
        device=cfg.embedding_device or "cpu",
    )

    vdb = ChromaVectorDB(persist_dir=str(tmp_path / "chroma"), collection_name="test")
    test_docs = _load_test_docs()
    _ingest_docs(vdb, embeddings, test_docs)
    assert vdb.count_documents() == len(test_docs)

    # hybrid search는 ChromaDB 미지원 → vector로 강제
    search_method = "vector" if cfg.retriever_search_method == "hybrid" else cfg.retriever_search_method
    retriever = VectorRetriever(
        vdb=vdb, embeddings=embeddings,
        top_k=cfg.retriever_top_k, search_method=search_method,
    )

    compressor = None
    if cfg.reranker_enabled:
        if cfg.reranker_type == "llm":
            llm_config = next((l for l in cfg.llms if l.name == cfg.reranker_llm), cfg.llms[0] if cfg.llms else None)
            if llm_config:
                compressor = LLMReranker(llm=create_chat_model(llm_config), top_k=cfg.reranker_top_k or 3)
        else:
            compressor = CrossEncoderCompressor(
                model_name=cfg.reranker_model,
                top_k=cfg.reranker_top_k,
                device=cfg.reranker_device or cfg.embedding_device,
            )

    return llm, retriever, compressor


def _compile_merged_graph(llm, retriever, compressor):
    """테스트 retriever/compressor를 주입해 병합 그래프(ReAct+RAG) 컴파일."""
    from unittest.mock import patch
    from maru_lang.graph.rag.graph import create_rag_graph

    with patch("maru_lang.graph.rag.graph.build_retriever", return_value=retriever), \
         patch("maru_lang.graph.rag.graph.build_compressor", return_value=compressor):
        return create_rag_graph(model=llm)


async def _run_full_pipeline(cfg, tmp_path):
    """config 로드 이후 전체 파이프라인 실행 + 검증.

    실제 LLM/임베딩/ChromaDB/검색/병합 그래프(agent → RAG → 응답)를 구동한다.
    """
    from langgraph.graph import StateGraph, END
    from langchain_core.messages import HumanMessage
    from maru_lang.graph.rag.state import RagState
    from maru_lang.graph.rag.nodes import (
        make_intent_node, make_keyword_node, make_retrieve_node,
        make_evaluate_node, evaluate_route, make_rerank_node, format_node,
    )

    llm, retriever, compressor = _build_stack(cfg, tmp_path)

    # 1) RAG 파이프라인(노드 팩토리 체인)으로 실제 검색/평가/포맷 검증
    rag_chain = StateGraph(RagState)
    rag_chain.add_node("intent", make_intent_node(llm))
    rag_chain.add_node("keywords", make_keyword_node(llm))
    rag_chain.add_node("retrieve", make_retrieve_node(retriever))
    rag_chain.add_node("evaluate", make_evaluate_node(
        method=cfg.evaluate_method, llm=llm if cfg.evaluate_method == "llm" else None))
    rag_chain.add_node("rerank", make_rerank_node(compressor))
    rag_chain.add_node("format", format_node)
    rag_chain.set_entry_point("intent")
    rag_chain.add_edge("intent", "keywords")
    rag_chain.add_edge("keywords", "retrieve")
    rag_chain.add_edge("retrieve", "evaluate")
    rag_chain.add_conditional_edges("evaluate", evaluate_route, {"rerank": "rerank", "retry": "keywords"})
    rag_chain.add_edge("rerank", "format")
    rag_chain.add_edge("format", END)
    rag_chain = rag_chain.compile()

    result = await asyncio.wait_for(
        rag_chain.ainvoke({
            "query": "강남 스시 맛집 추천해줘",
            "rewritten_query": "", "keywords": [], "documents": [], "result": "",
            "team_ids": [1], "retry_count": 0, "evaluation": "",
            "excluded_doc_ids": [], "rag_log": [],
        }),
        timeout=60.0,
    )
    assert len(result["documents"]) > 0, "실제 벡터 검색으로 문서가 반환되어야 함"
    assert result["result"], "RAG 결과가 생성되어야 함"
    assert result["evaluation"] in ("pass", "max_retry")

    # 2) 병합 그래프(ReAct + RAG) 실행 — checkpointer 사용이므로 thread_id 필수
    graph = _compile_merged_graph(llm, retriever, compressor)
    nodes = set(graph.get_graph().nodes)
    assert {"context_builder", "route", "generate", "search_entry", "summarize", "memory_extractor"}.issubset(nodes)

    chat_result = await asyncio.wait_for(
        graph.ainvoke(
            {"messages": [HumanMessage(content="강남 스시 맛집 추천해줘")],
             "team_ids": [1], "team_names": ["test-team"]},
            config={"configurable": {"thread_id": "e2e-test"}},
        ),
        timeout=60.0,
    )
    assert len(chat_result["messages"]) >= 2, "최소 HumanMessage + AIMessage가 있어야 함"


def _load_user_cfg(monkeypatch):
    """`maru test`가 만든 임시 config(MARU_TEST_CONFIG_DIR)를 로드. 없으면 skip."""
    cfg_dir = os.getenv("MARU_TEST_CONFIG_DIR")
    if not cfg_dir:
        pytest.skip("MARU_TEST_CONFIG_DIR not set — run via `maru test`.")
    monkeypatch.chdir(cfg_dir)
    return reload_config()


@pytest.mark.integration
@pytest.mark.llm_smoke
class TestLLMSmoke:
    """실제 LLM 호출이 필요한 스모크 모음 — `maru test`로 선택한 provider/모델 실행.

    CI의 `pytest -m integration`에서는 MARU_TEST_CONFIG_DIR가 없어 전부 skip된다.
    """

    async def test_pipeline(self, tmp_path, monkeypatch):
        """임베딩→검색→agent tool_call→RAG→응답 전체 파이프라인."""
        cfg = _load_user_cfg(monkeypatch)
        await _run_full_pipeline(cfg, tmp_path)

    async def test_simple_query(self, tmp_path, monkeypatch):
        """단순 질의에 답변을 생성한다."""
        from langchain_core.messages import HumanMessage
        cfg = _load_user_cfg(monkeypatch)
        graph = _compile_merged_graph(*_build_stack(cfg, tmp_path))
        res = await asyncio.wait_for(
            graph.ainvoke(
                {"messages": [HumanMessage(content="MARU 프로젝트가 뭐야?")],
                 "team_ids": [1], "team_names": ["test-team"]},
                config={"configurable": {"thread_id": "smoke-simple"}},
            ),
            timeout=90.0,
        )
        assert len(res["messages"][-1].content) > 5

    async def test_multi_turn(self, tmp_path, monkeypatch):
        """같은 thread_id로 후속 질문 시 그래프가 맥락을 유지한다."""
        from langchain_core.messages import HumanMessage
        cfg = _load_user_cfg(monkeypatch)
        graph = _compile_merged_graph(*_build_stack(cfg, tmp_path))
        conf = {"configurable": {"thread_id": "smoke-multi"}}
        await asyncio.wait_for(graph.ainvoke(
            {"messages": [HumanMessage(content="강남 스시 맛집 알려줘")],
             "team_ids": [1], "team_names": ["test-team"]}, config=conf), timeout=90.0)
        r2 = await asyncio.wait_for(graph.ainvoke(
            {"messages": [HumanMessage(content="방금 답변을 더 자세히 설명해줘")],
             "team_ids": [1], "team_names": ["test-team"]}, config=conf), timeout=90.0)
        assert len(r2["messages"][-1].content) > 5

    async def test_direct_answer(self, tmp_path, monkeypatch):
        """검색이 불필요한 질문도 응답을 생성한다(tool 호출 여부는 LLM 재량)."""
        from langchain_core.messages import HumanMessage
        cfg = _load_user_cfg(monkeypatch)
        graph = _compile_merged_graph(*_build_stack(cfg, tmp_path))
        res = await asyncio.wait_for(
            graph.ainvoke(
                {"messages": [HumanMessage(content="'안녕하세요'라고만 답해줘.")],
                 "team_ids": [1], "team_names": ["test-team"]},
                config={"configurable": {"thread_id": "smoke-direct"}},
            ),
            timeout=90.0,
        )
        assert res["messages"][-1].content

    async def test_feedback_flow(self, tmp_path, monkeypatch):
        """function=feedback: 답변→score interrupt→낮은점수 resume→reason interrupt→resume→저장."""
        from langchain_core.messages import HumanMessage
        from langgraph.types import Command
        cfg = _load_user_cfg(monkeypatch)
        graph = _compile_merged_graph(*_build_stack(cfg, tmp_path))
        conf = {"configurable": {"thread_id": "smoke-fb"}}

        await asyncio.wait_for(graph.ainvoke(
            {"messages": [HumanMessage(content="강남 스시 맛집 추천")],
             "team_ids": [1], "team_names": ["test-team"], "function": "feedback"},
            config=conf), timeout=90.0)
        # score interrupt → 낮은 점수(2)로 resume → reason interrupt → 사유 resume
        await asyncio.wait_for(graph.ainvoke(Command(resume="2"), config=conf), timeout=90.0)
        await asyncio.wait_for(graph.ainvoke(Command(resume="정보가 부족했어요"), config=conf), timeout=90.0)

        snap = await graph.aget_state(conf)
        assert snap.values.get("feedback_score") == 2
        assert snap.values.get("feedback_reason")

    async def test_user_memory_recall(self, tmp_path, monkeypatch):
        """사용자가 말한 사실을 추출·저장하고, 다음 턴(다른 thread)에서 회상한다."""
        from langchain_core.messages import HumanMessage
        from maru_lang.core.relation_db.models.auth import User
        from maru_lang.services.session import create_session

        cfg = _load_user_cfg(monkeypatch)
        graph = _compile_merged_graph(*_build_stack(cfg, tmp_path))

        user = await User.create(name="t", email="mem@example.com")
        session = await create_session(user)
        base = {"team_ids": [1], "team_names": ["test-team"],
                "session_id": session.id, "user_id": user.id}

        # Turn 1: state a durable fact → memory_extractor should persist it.
        await asyncio.wait_for(graph.ainvoke(
            {**base, "messages": [HumanMessage(content="내 이름은 김지훈이야. 기억해줘.")]},
            config={"configurable": {"thread_id": f"{session.id}:t1"}}), timeout=90.0)

        # Turn 2: fresh thread → recall comes only from DB via context_builder.
        res = await asyncio.wait_for(graph.ainvoke(
            {**base, "messages": [HumanMessage(content="내 이름이 뭐야?")]},
            config={"configurable": {"thread_id": f"{session.id}:t2"}}), timeout=90.0)

        assert "김지훈" in res["messages"][-1].content
