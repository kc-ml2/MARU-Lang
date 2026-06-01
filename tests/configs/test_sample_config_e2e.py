"""Sample config E2E integration test — mock 없음.

tests/sample_config/*.yaml를 순회하면서:
1. config 로드
2. 실제 LLM 생성 (API key 필요)
3. 실제 HuggingFace 임베딩 모델 로드
4. 실제 ChromaDB에 맛집 문서 인제스트
5. 실제 벡터 검색 + 실제 reranker
6. 실제 RAG 파이프라인 실행
7. 실제 Chat Graph 컴파일 + 실행 (system prompt, tool routing)

API key 없으면 해당 config 테스트는 실패함.
실행: pytest tests/configs/test_sample_config_e2e.py -m integration
"""
import asyncio
import os
import shutil
from pathlib import Path

import pytest
import yaml as _yaml

import maru_lang.configs.manager as cfg_mod
import maru_lang.core.llm as llm_mod
from maru_lang.configs.manager import reload_config
from maru_lang.core.llm.server_manager import LLMManager
from maru_lang.core.vector_db.chroma import ChromaVectorDB
from maru_lang.graph.ingest.embedder import get_embeddings
from maru_lang.graph.rag.retriever.vector import VectorRetriever

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_config"
SAMPLES = sorted(SAMPLE_DIR.glob("*.yaml"))
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


_PROVIDER_GATE_ENV = {
    # Hosted LLM APIs — require API key
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    # Self-hosted LLM servers — require explicit opt-in to avoid connection hangs
    # when no local server is running. Users set these to their actual endpoint
    # (e.g. http://localhost:11434) to enable the corresponding yaml fixtures.
    "ollama": "OLLAMA_BASE_URL",
    "vllm": "VLLM_BASE_URL",
}


def _skip_if_missing_provider_keys(yaml_path: Path) -> None:
    """Skip the test when the yaml references a provider without the required gate env.

    Prevents accidental API-cost / connection-hang when someone runs
    `pytest -m integration` locally without any keys or local servers.
    """
    raw = _yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    providers = {
        (llm or {}).get("provider")
        for llm in (raw.get("llms") or [])
        if (llm or {}).get("enabled", True)
    }
    providers.discard(None)

    missing = [
        env for p in providers
        if (env := _PROVIDER_GATE_ENV.get(p)) and not os.getenv(env)
    ]
    if missing:
        pytest.skip(f"Missing gate env(s): {', '.join(missing)} — set to enable this config.")


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("yaml_path", SAMPLES, ids=[p.stem for p in SAMPLES])
async def test_config_full_pipeline(yaml_path, tmp_path, monkeypatch):
    """config별 전체 파이프라인 — 실제 임베딩, 실제 검색, 실제 LLM, 실제 reranker."""
    _skip_if_missing_provider_keys(yaml_path)
    from maru_lang.graph.rag.graph import create_rag_graph

    # 1) config 로드
    app_dir = tmp_path / "maru_app"
    app_dir.mkdir()
    shutil.copy(yaml_path, app_dir / "maru_config.yaml")
    monkeypatch.chdir(tmp_path)
    cfg = reload_config()

    # 2) 실제 LLM 생성
    manager = LLMManager(cfg.llms)
    enabled = [llm for llm in cfg.llms if llm.enabled]
    assert len(manager.clients) == len(enabled)
    llm = manager.get_model()

    # 3) 실제 임베딩 모델 로드
    embeddings = get_embeddings(
        model_name=cfg.embedding_model,
        device=cfg.embedding_device or "cpu",
    )

    # 4) 실제 ChromaDB 생성 + 문서 인제스트
    chroma_dir = str(tmp_path / "chroma")
    vdb = ChromaVectorDB(persist_dir=chroma_dir, collection_name="test")
    test_docs = _load_test_docs()
    _ingest_docs(vdb, embeddings, test_docs)
    assert vdb.count_documents() == len(test_docs)

    # 5) 실제 Retriever 생성
    # hybrid search는 ChromaDB 미지원 → vector로 강제
    search_method = "vector" if cfg.retriever_search_method == "hybrid" else cfg.retriever_search_method
    retriever = VectorRetriever(
        vdb=vdb,
        embeddings=embeddings,
        top_k=cfg.retriever_top_k,
        search_method=search_method,
    )

    # 6) 실제 Compressor (reranker) 생성
    from maru_lang.core.llm.client import create_chat_model
    from maru_lang.graph.rag.reranker import CrossEncoderCompressor, LLMReranker

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

    # 7) RAG 파이프라인 검증 — 노드 팩토리로 retrieval 체인 구성(주입한 실제 retriever 사용)
    from langgraph.graph import StateGraph, END
    from maru_lang.graph.rag.state import RagState
    from maru_lang.graph.rag.nodes import (
        make_intent_node, make_keyword_node, make_retrieve_node,
        make_evaluate_node, evaluate_route, make_rerank_node, format_node,
    )

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
            "rewritten_query": "",
            "keywords": [],
            "documents": [],
            "result": "",
            "team_ids": [1],
            "retry_count": 0,
            "evaluation": "",
            "excluded_doc_ids": [],
            "rag_log": [],
        }),
        timeout=60.0,
    )

    # 8) RAG 검증
    assert len(result["documents"]) > 0, "실제 벡터 검색으로 문서가 반환되어야 함"
    assert result["result"], "RAG 결과가 생성되어야 함"
    assert result["evaluation"] in ("pass", "max_retry")

    # 9) 병합 그래프(ReAct + RAG) 컴파일 + 실행 — 테스트 retriever/compressor 주입
    from unittest.mock import patch
    from langchain_core.messages import HumanMessage

    with patch(
        "maru_lang.graph.rag.graph._build_retriever_and_compressor",
        return_value=(retriever, compressor),
    ):
        graph = create_rag_graph(model=llm)

    # 구조 검증: 단일 그래프에 agent + 검색 진입/RAG 노드가 모두 존재
    nodes = set(graph.get_graph().nodes)
    assert "agent" in nodes
    assert "search_entry" in nodes
    assert "format" in nodes

    # 실행 (실제 LLM이 tool call → RAG 노드 → 응답)
    chat_result = await asyncio.wait_for(
        graph.ainvoke({
            "messages": [HumanMessage(content="강남 스시 맛집 추천해줘")],
            "team_ids": [1],
            "team_names": ["test-team"],
        }),
        timeout=60.0,
    )

    assert len(chat_result["messages"]) >= 2, "최소 HumanMessage + AIMessage가 있어야 함"
