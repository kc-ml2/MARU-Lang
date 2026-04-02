"""Ingest pipeline LangGraph tests

Run: venv/bin/python -m pytest tests/test_ingest.py -v
"""
import sys
import types
import tempfile
from pathlib import Path

import pytest

# Bypass maru_lang.__init__ full app loading
if "maru_lang" not in sys.modules:
    _fake = types.ModuleType("maru_lang")
    _fake.__path__ = ["maru_lang"]
    sys.modules["maru_lang"] = _fake

from maru_lang.constants import SUPPORTED_EXTENSIONS
from maru_lang.graph.ingest.loader import load_file, is_supported
from maru_lang.graph.ingest.splitter import create_splitter, split_documents
from maru_lang.graph.ingest.state import IngestState
from maru_lang.graph.ingest.graph import create_ingest_graph


# ─── Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def sample_txt(tmp_path):
    f = tmp_path / "sample.txt"
    f.write_text("First paragraph. Description of the MARU project.\n\n"
                 "Second paragraph. Migrated to LangGraph.\n\n"
                 "Third paragraph. Supports Korean NLP.")
    return f


@pytest.fixture
def sample_md(tmp_path):
    f = tmp_path / "readme.md"
    f.write_text("# MARU Project\n\n"
                 "## Overview\n"
                 "MARU is a RAG-based chatbot system.\n\n"
                 "## Features\n"
                 "- Multi-agent architecture\n"
                 "- Korean NLP support\n"
                 "- LangGraph integration\n")
    return f


@pytest.fixture
def sample_csv(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("name,role,team\n"
                 "Alice,Engineer,Backend\n"
                 "Bob,Designer,Frontend\n"
                 "Charlie,PM,Product\n")
    return f


@pytest.fixture
def long_text(tmp_path):
    """Long text for chunking tests"""
    f = tmp_path / "long.txt"
    paragraphs = [f"Paragraph {i}. " + "This is a test sentence. " * 20 for i in range(10)]
    f.write_text("\n\n".join(paragraphs))
    return f


# ─── Constants ────────────────────────────────────────────────


class TestConstants:
    def test_supported_extensions_has_common_formats(self):
        for ext in [".pdf", ".docx", ".txt", ".md", ".csv", ".json", ".html"]:
            assert ext in SUPPORTED_EXTENSIONS

    def test_supported_extensions_has_code_formats(self):
        for ext in [".py", ".js", ".ts", ".go"]:
            assert ext in SUPPORTED_EXTENSIONS


# ─── Loader ───────────────────────────────────────────────────


class TestLoader:
    def test_load_txt(self, sample_txt):
        docs = load_file(sample_txt)
        assert len(docs) >= 1
        assert "MARU" in docs[0].page_content

    def test_load_md(self, sample_md):
        docs = load_file(sample_md)
        assert len(docs) >= 1
        assert "MARU" in docs[0].page_content

    def test_load_csv(self, sample_csv):
        docs = load_file(sample_csv)
        assert len(docs) >= 1
        content = " ".join(d.page_content for d in docs)
        assert "Alice" in content

    def test_is_supported(self, tmp_path):
        assert is_supported(tmp_path / "test.txt")
        assert is_supported(tmp_path / "test.pdf")
        assert is_supported(tmp_path / "test.py")
        assert not is_supported(tmp_path / "test.xyz")
        assert not is_supported(tmp_path / "test.bin")

    def test_load_unknown_as_text(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("def hello():\n    print('world')")
        docs = load_file(f)
        assert "hello" in docs[0].page_content


# ─── Splitter ─────────────────────────────────────────────────


class TestSplitter:
    def test_create_splitter_defaults(self):
        splitter = create_splitter()
        assert splitter._chunk_size == 1000
        assert splitter._chunk_overlap == 200

    def test_create_splitter_custom(self):
        splitter = create_splitter(chunk_size=500, chunk_overlap=100)
        assert splitter._chunk_size == 500
        assert splitter._chunk_overlap == 100

    def test_split_short_text(self, sample_txt):
        docs = load_file(sample_txt)
        chunks = split_documents(docs, chunk_size=1000, chunk_overlap=0)
        assert len(chunks) >= 1

    def test_split_long_text(self, long_text):
        docs = load_file(long_text)
        chunks = split_documents(docs, chunk_size=200, chunk_overlap=50)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk.page_content) <= 250

    def test_split_preserves_content(self, sample_txt):
        docs = load_file(sample_txt)
        chunks = split_documents(docs, chunk_size=50, chunk_overlap=10)
        merged = "".join(c.page_content for c in chunks)
        assert "MARU" in merged
        assert "LangGraph" in merged


# ─── Graph Compilation ────────────────────────────────────────


class TestIngestGraph:
    def test_graph_compiles(self):
        graph = create_ingest_graph()
        nodes = list(graph.get_graph().nodes.keys())
        assert "sync_document" in nodes
        assert "process_document" in nodes

    def test_graph_has_correct_flow(self):
        graph = create_ingest_graph()
        edges = str(graph.get_graph().edges)
        assert "sync_document" in edges
        assert "process_document" in edges

    def test_state_schema(self):
        keys = list(IngestState.__annotations__.keys())
        assert "file" in keys
        assert "team_id" in keys
        assert "messages" in keys
        assert "total_chunks" in keys
        assert "embedder_model" in keys


# ─── E2E (Load -> Split) ────────────────────────────────────


class TestLoadAndSplit:
    """Loader + Splitter integration tests"""

    def test_txt_e2e(self, sample_txt):
        docs = load_file(sample_txt)
        chunks = split_documents(docs)
        assert len(chunks) >= 1
        assert all(c.page_content.strip() for c in chunks)

    def test_md_e2e(self, sample_md):
        docs = load_file(sample_md)
        chunks = split_documents(docs)
        assert len(chunks) >= 1

    def test_csv_e2e(self, sample_csv):
        docs = load_file(sample_csv)
        chunks = split_documents(docs)
        assert len(chunks) >= 1

    def test_multiple_files(self, sample_txt, sample_md):
        all_docs = load_file(sample_txt) + load_file(sample_md)
        chunks = split_documents(all_docs)
        merged = " ".join(c.page_content for c in chunks)
        assert "MARU" in merged
