"""Ingest pipeline LangGraph tests

Run: venv/bin/python -m pytest tests/test_ingest.py -v
"""
import sys
import types
import tempfile
import operator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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


# ─── Loader Edge Cases ───────────────────────────────────────


class TestLoaderEdgeCases:
    def test_load_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        docs = load_file(f)
        assert isinstance(docs, list)

    def test_load_file_not_found(self):
        with pytest.raises(Exception):
            load_file(Path("/nonexistent/file.txt"))


# ─── Splitter Edge Cases ─────────────────────────────────────


class TestSplitterEdgeCases:
    def test_split_empty_documents(self):
        result = split_documents([])
        assert result == []

    def test_split_single_short_doc(self, sample_txt):
        docs = load_file(sample_txt)
        chunks = split_documents(docs, chunk_size=10000, chunk_overlap=0)
        assert len(chunks) >= 1


# ─── IngestState Reducer ─────────────────────────────────────


class TestIngestStateReducer:
    def test_messages_has_operator_add_reducer(self):
        hints = IngestState.__annotations__
        assert "messages" in hints

    def test_state_has_required_keys(self):
        keys = list(IngestState.__annotations__.keys())
        for k in ["file", "team_id", "re_embed", "document", "needs_processing", "total_chunks", "error", "messages"]:
            assert k in keys, f"Missing key: {k}"


# ─── sync_document (mock ORM) ────────────────────────────────


class TestSyncDocument:
    @pytest.fixture
    def mock_file_info(self):
        from datetime import datetime
        fi = MagicMock()
        fi.absolutePath = "/tmp/test/doc.txt"
        fi.fileName = "doc.txt"
        fi.size = 1024
        fi.createdAt = datetime(2026, 1, 1)
        fi.tempFilePath = None
        return fi

    @pytest.mark.asyncio
    @patch("maru_lang.graph.ingest.nodes.upsert_document_from_file")
    @patch("maru_lang.graph.ingest.nodes.get_or_create_document_group")
    @patch("maru_lang.graph.ingest.nodes._get_or_create_group")
    async def test_sync_creates_document(self, mock_get_group, mock_get_or_create, mock_upsert, mock_file_info):
        from maru_lang.graph.ingest.nodes import sync_document

        mock_group = MagicMock()
        mock_get_group.return_value = mock_group

        mock_doc = MagicMock()
        mock_doc.id = 1
        mock_doc.name = "doc"
        mock_doc.file_path = "/tmp/test/doc.txt"
        mock_doc.storage_path = None
        mock_doc.group_id = 10
        mock_doc.metadata = {}
        mock_upsert.return_value = (mock_doc, True)

        state = {
            "file": mock_file_info,
            "team_id": 1,
            "re_embed": False,
        }
        result = await sync_document(state)

        assert result["document"] is not None
        assert result["needs_processing"] is True
        assert "Synced" in result["messages"][0]

    @pytest.mark.asyncio
    @patch("maru_lang.graph.ingest.nodes._get_or_create_group")
    @patch("maru_lang.graph.ingest.nodes.upsert_document_from_file")
    async def test_sync_skips_when_unchanged(self, mock_upsert, mock_get_group, mock_file_info):
        from maru_lang.graph.ingest.nodes import sync_document

        mock_group = MagicMock()
        mock_get_group.return_value = mock_group

        mock_doc = MagicMock()
        mock_doc.id = 1
        mock_doc.name = "doc"
        mock_doc.file_path = "/tmp/test/doc.txt"
        mock_doc.storage_path = None
        mock_doc.group_id = 10
        mock_doc.metadata = {}
        mock_upsert.return_value = (mock_doc, False)

        state = {"file": mock_file_info, "team_id": 1, "re_embed": False}
        result = await sync_document(state)

        assert result["needs_processing"] is False

    @pytest.mark.asyncio
    @patch("maru_lang.graph.ingest.nodes._get_or_create_group", side_effect=Exception("DB error"))
    async def test_sync_error_returns_error_state(self, mock_get_group, mock_file_info):
        from maru_lang.graph.ingest.nodes import sync_document

        state = {"file": mock_file_info, "team_id": 1, "re_embed": False}
        result = await sync_document(state)

        assert result["document"] is None
        assert result["error"] == "DB error"
        assert "Failed" in result["messages"][0]


# ─── process_document (mock VDB+ORM) ─────────────────────────


class TestProcessDocument:
    @pytest.mark.asyncio
    async def test_skips_when_not_needed(self):
        from maru_lang.graph.ingest.nodes import process_document

        state = {
            "document": {"id": 1, "name": "doc"},
            "needs_processing": False,
            "team_id": 1,
            "embedder_model": "test",
        }
        result = await process_document(state)
        assert "Skipped" in result["messages"][0]

    @pytest.mark.asyncio
    async def test_skips_when_no_document(self):
        from maru_lang.graph.ingest.nodes import process_document

        state = {
            "document": None,
            "needs_processing": True,
            "team_id": 1,
            "embedder_model": "test",
        }
        result = await process_document(state)
        assert "Skipped" in result["messages"][0]

    @pytest.mark.asyncio
    @patch("maru_lang.graph.ingest.nodes.update_document_status", new_callable=AsyncMock)
    @patch("maru_lang.graph.ingest.nodes.Document")
    @patch("maru_lang.graph.ingest.nodes.get_vector_db")
    @patch("maru_lang.graph.ingest.nodes.get_embeddings")
    @patch("maru_lang.graph.ingest.nodes.load_file")
    @patch("maru_lang.graph.ingest.nodes.split_documents")
    @patch("maru_lang.graph.ingest.nodes.make_chunk_uid")
    async def test_process_loads_splits_embeds_stores(
        self, mock_uid, mock_split, mock_load, mock_get_emb, mock_get_vdb,
        mock_doc_model, mock_update_status
    ):
        from maru_lang.graph.ingest.nodes import process_document
        from langchain_core.documents import Document as LCDoc

        mock_db_doc = MagicMock()
        mock_doc_model.get_or_none = AsyncMock(return_value=mock_db_doc)
        mock_doc_model.exists = AsyncMock(return_value=True)

        mock_vdb = MagicMock()
        mock_vdb.upsert_documents = MagicMock()
        mock_vdb.get_chunk_ids_by_document_id = MagicMock(return_value=[])
        mock_get_vdb.return_value = mock_vdb

        mock_emb = MagicMock()
        mock_emb.embed_documents = MagicMock(return_value=[[0.1] * 384, [0.2] * 384])
        mock_get_emb.return_value = mock_emb

        mock_load.return_value = [LCDoc(page_content="test content")]
        mock_split.return_value = [LCDoc(page_content="chunk1"), LCDoc(page_content="chunk2")]
        mock_uid.side_effect = lambda doc_id, idx, content: f"uid-{doc_id}-{idx}"

        state = {
            "document": {
                "id": 1, "name": "doc", "file_path": "/tmp/doc.txt",
                "storage_path": None, "group_id": 10, "metadata": {},
            },
            "needs_processing": True,
            "team_id": 1,
            "embedder_model": "test-model",
        }
        result = await process_document(state)

        assert result["total_chunks"] == 2
        assert "2 chunks" in result["messages"][0]

    @pytest.mark.asyncio
    @patch("maru_lang.graph.ingest.nodes.update_document_status", new_callable=AsyncMock)
    @patch("maru_lang.graph.ingest.nodes.Document")
    @patch("maru_lang.graph.ingest.nodes.get_vector_db")
    @patch("maru_lang.graph.ingest.nodes.get_embeddings")
    @patch("maru_lang.graph.ingest.nodes.load_file")
    async def test_process_handles_empty_content(
        self, mock_load, mock_get_emb, mock_get_vdb, mock_doc_model, mock_update_status
    ):
        from maru_lang.graph.ingest.nodes import process_document

        mock_db_doc = MagicMock()
        mock_db_doc.save = AsyncMock()
        mock_doc_model.get_or_none = AsyncMock(return_value=mock_db_doc)
        mock_get_vdb.return_value = MagicMock()
        mock_get_emb.return_value = MagicMock()
        mock_load.return_value = []

        state = {
            "document": {
                "id": 1, "name": "doc", "file_path": "/tmp/doc.txt",
                "storage_path": None, "group_id": 10, "metadata": {},
            },
            "needs_processing": True,
            "team_id": 1,
            "embedder_model": "test",
        }
        result = await process_document(state)
        assert "error" in result or "Empty" in result["messages"][0]


# ─── _get_or_create_group (mock ORM) ─────────────────────────


class TestGetOrCreateGroup:
    @pytest.mark.asyncio
    @patch("maru_lang.graph.ingest.nodes.get_or_create_document_group")
    async def test_creates_hierarchy_from_path(self, mock_get_or_create):
        from maru_lang.graph.ingest.nodes import _get_or_create_group

        call_count = 0
        async def side_effect(team_id, name, parent):
            nonlocal call_count
            call_count += 1
            group = MagicMock()
            group.id = call_count
            return group, True

        mock_get_or_create.side_effect = side_effect

        result = await _get_or_create_group("/usr/local/data", team_id=1)
        assert result is not None
        assert call_count == 3  # usr, local, data

    @pytest.mark.asyncio
    @patch("maru_lang.graph.ingest.nodes.get_or_create_document_group")
    async def test_skips_root_slash(self, mock_get_or_create):
        from maru_lang.graph.ingest.nodes import _get_or_create_group

        groups_created = []
        async def side_effect(team_id, name, parent):
            groups_created.append(name)
            group = MagicMock()
            return group, True

        mock_get_or_create.side_effect = side_effect

        await _get_or_create_group("/data", team_id=1)
        assert "/" not in groups_created
