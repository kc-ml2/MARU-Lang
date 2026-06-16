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
        graph = create_ingest_graph(vdb=MagicMock(), embeddings=MagicMock())
        nodes = list(graph.get_graph().nodes.keys())
        assert "sync_document" in nodes
        assert "parse_document" in nodes
        assert "process_document" in nodes

    def test_graph_has_correct_flow(self):
        graph = create_ingest_graph(vdb=MagicMock(), embeddings=MagicMock())
        pairs = {(e.source, e.target) for e in graph.get_graph().edges}
        # Exact wiring: start → sync → parse → process → end (no skipped/reversed edge).
        assert pairs == {
            ("__start__", "sync_document"),
            ("sync_document", "parse_document"),
            ("parse_document", "process_document"),
            ("process_document", "__end__"),
        }

    def test_state_schema(self):
        keys = list(IngestState.__annotations__.keys())
        assert "file" in keys
        assert "team_id" in keys
        assert "messages" in keys
        assert "total_chunks" in keys


# ─── Graph execution (compiled graph, nodes chained) ─────────


class TestIngestGraphExecution:
    """Invoke the compiled graph end to end — verifies node chaining, state
    threading, and error propagation that node-level tests can't catch."""

    @staticmethod
    def _graph(vectors=None):
        from maru_lang.graph.ingest.graph import create_ingest_graph
        vdb = MagicMock()
        vdb.get_chunk_ids_by_document_id = MagicMock(return_value=[])
        emb = MagicMock()
        emb.embed_documents = MagicMock(return_value=vectors or [[0.1, 0.2, 0.3]])
        return create_ingest_graph(vdb=vdb, embeddings=emb), vdb, emb

    @staticmethod
    def _presynced_input(doc_id="d1"):
        from maru_lang.graph.ingest.state import build_ingest_input
        return build_ingest_input(
            1,
            document={"id": doc_id, "name": "doc", "file_path": "/tmp/x.pdf",
                      "storage_path": None, "group_id": 5, "metadata": {}},
            needs_processing=True,
        )

    @staticmethod
    def _doc_mock():
        """Patched Document model with awaitable filter().update()/delete()."""
        m = MagicMock()
        db_doc = MagicMock(); db_doc.metadata = {}
        m.get_or_none = AsyncMock(return_value=db_doc)
        flt = MagicMock()
        flt.update = AsyncMock(return_value=1)
        flt.delete = AsyncMock(return_value=1)
        m.filter = MagicMock(return_value=flt)
        return m, db_doc

    @pytest.mark.asyncio
    @patch("maru_lang.graph.ingest.nodes.make_chunk_uid", side_effect=lambda i, x, c: f"{i}-{x}")
    @patch("maru_lang.graph.ingest.nodes.split_documents")
    @patch("maru_lang.graph.ingest.nodes.parse_file")
    @patch("maru_lang.graph.ingest.nodes.try_activate", new_callable=AsyncMock)
    @patch("maru_lang.graph.ingest.nodes.begin_processing", new_callable=AsyncMock)
    @patch("maru_lang.graph.ingest.nodes.Document")
    async def test_presynced_flow_chains_sync_skip_parse_process(
        self, mock_doc, mock_begin, mock_try, mock_parse, mock_split, mock_uid
    ):
        from langchain_core.documents import Document as LCDoc
        m, db_doc = self._doc_mock()
        mock_doc.get_or_none = m.get_or_none
        mock_doc.filter = m.filter
        mock_begin.return_value = True
        mock_try.return_value = True  # PROCESSING -> ACTIVE committed
        mock_parse.return_value = ([LCDoc(page_content="body")], "kordoc")
        mock_split.return_value = [LCDoc(page_content="c1"), LCDoc(page_content="c2")]

        graph, vdb, emb = self._graph(vectors=[[0.1] * 3, [0.2] * 3])
        result = await graph.ainvoke(self._presynced_input())

        # sync skipped (document pre-set), parse ran, process embedded + stored.
        assert result["parser"] == "kordoc"
        assert result["total_chunks"] == 2
        assert result["error"] is None
        assert emb.embed_documents.called and vdb.upsert_documents.called
        # parser recorded via field-scoped metadata update
        m.filter().update.assert_any_await(metadata={"parser": "kordoc"})
        joined = " ".join(result["messages"])  # reducer accumulates across nodes
        assert "Already synced" in joined and "Parsed (kordoc)" in joined

    @pytest.mark.asyncio
    @patch("maru_lang.graph.ingest.nodes.fail_processing", new_callable=AsyncMock)
    @patch("maru_lang.graph.ingest.nodes.parse_file")
    @patch("maru_lang.graph.ingest.nodes.begin_processing", new_callable=AsyncMock)
    @patch("maru_lang.graph.ingest.nodes.Document")
    async def test_parse_error_propagates_and_skips_processing(
        self, mock_doc, mock_begin, mock_parse, mock_fail
    ):
        m, _ = self._doc_mock()
        mock_doc.get_or_none = m.get_or_none
        mock_doc.filter = m.filter
        mock_begin.return_value = True
        mock_parse.side_effect = RuntimeError("boom")

        graph, vdb, emb = self._graph()
        result = await graph.ainvoke(self._presynced_input("d2"))

        # Error survives to the final state; process_document must not embed.
        assert result["error"] == "boom"
        assert result["total_chunks"] == 0
        assert not emb.embed_documents.called
        assert not vdb.upsert_documents.called

    @pytest.mark.asyncio
    @patch("maru_lang.graph.ingest.nodes.make_chunk_uid", side_effect=lambda i, x, c: f"{i}-{x}")
    @patch("maru_lang.graph.ingest.nodes.split_documents")
    @patch("maru_lang.graph.ingest.nodes.parse_file")
    @patch("maru_lang.graph.ingest.nodes.try_activate", new_callable=AsyncMock)
    @patch("maru_lang.graph.ingest.nodes.begin_processing", new_callable=AsyncMock)
    @patch("maru_lang.graph.ingest.nodes.upsert_document_from_file")
    @patch("maru_lang.graph.ingest.nodes.get_or_create_group_hierarchy")
    @patch("maru_lang.graph.ingest.nodes.Document")
    async def test_file_entry_flow_runs_sync_then_parse_process(
        self, mock_doc, mock_group, mock_upsert, mock_begin, mock_try, mock_parse, mock_split, mock_uid
    ):
        from datetime import datetime
        from langchain_core.documents import Document as LCDoc
        from maru_lang.graph.ingest.state import build_ingest_input

        synced = MagicMock()
        synced.id = "d3"; synced.name = "doc"; synced.file_path = "/tmp/z.pdf"
        synced.storage_path = None; synced.group_id = 7; synced.metadata = {}
        synced.save = AsyncMock()
        mock_upsert.return_value = (synced, True)   # unchanged check -> needs_processing
        mock_group.return_value = MagicMock()

        m, _ = self._doc_mock()
        mock_doc.get_or_none = m.get_or_none
        mock_doc.filter = m.filter
        mock_begin.return_value = True
        mock_try.return_value = True
        mock_parse.return_value = ([LCDoc(page_content="body")], "langchain")
        mock_split.return_value = [LCDoc(page_content="c1")]

        graph, vdb, emb = self._graph()
        fi = MagicMock()
        fi.absolutePath = "/tmp/z.pdf"; fi.fileName = "z.pdf"; fi.size = 10
        fi.createdAt = datetime(2026, 1, 1); fi.tempFilePath = None

        result = await graph.ainvoke(build_ingest_input(1, file=fi))

        mock_group.assert_called()  # sync actually ran (not skipped)
        assert result["parser"] == "langchain"
        assert result["total_chunks"] == 1
        assert vdb.upsert_documents.called


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
    @patch("maru_lang.graph.ingest.nodes.get_or_create_group_hierarchy")
    async def test_sync_creates_document(self, mock_get_group, mock_upsert, mock_file_info):
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
    @patch("maru_lang.graph.ingest.nodes.get_or_create_group_hierarchy")
    async def test_sync_skips_when_already_synced(self, mock_get_group):
        """API/worker path: document is pre-synced, so sync passes through."""
        from maru_lang.graph.ingest.nodes import sync_document

        state = {
            "file": None,
            "team_id": 1,
            "re_embed": False,
            "document": {"id": "abc", "name": "doc"},
            "needs_processing": True,
        }
        result = await sync_document(state)

        # No DB/group work — and it must not clobber the pre-set document/flag.
        mock_get_group.assert_not_called()
        assert "document" not in result  # left as-is in state
        assert "Already synced" in result["messages"][0]

    @pytest.mark.asyncio
    @patch("maru_lang.graph.ingest.nodes.get_or_create_group_hierarchy")
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
    @patch("maru_lang.graph.ingest.nodes.get_or_create_group_hierarchy", side_effect=Exception("DB error"))
    async def test_sync_error_returns_error_state(self, mock_get_group, mock_file_info):
        from maru_lang.graph.ingest.nodes import sync_document

        state = {"file": mock_file_info, "team_id": 1, "re_embed": False}
        result = await sync_document(state)

        assert result["document"] is None
        assert result["error"] == "DB error"
        assert "Failed" in result["messages"][0]


# ─── process_document (mock VDB+ORM) ─────────────────────────


class TestProcessDocument:
    @staticmethod
    def _node(vdb=None, embeddings=None):
        """process_document with injected deps (mocks by default)."""
        from maru_lang.graph.ingest.nodes import make_process_document_node
        return make_process_document_node(vdb or MagicMock(), embeddings or MagicMock())

    @pytest.mark.asyncio
    async def test_skips_when_not_needed(self):
        state = {
            "document": {"id": 1, "name": "doc"},
            "needs_processing": False,
            "team_id": 1,
        }
        result = await self._node()(state)
        assert "Skipped" in result["messages"][0]

    @pytest.mark.asyncio
    async def test_skips_when_no_document(self):
        state = {
            "document": None,
            "needs_processing": True,
            "team_id": 1,
        }
        result = await self._node()(state)
        assert "Skipped" in result["messages"][0]

    @pytest.mark.asyncio
    async def test_skips_when_no_parsed_docs(self):
        state = {
            "document": {"id": 1, "name": "doc"},
            "needs_processing": True,
            "parsed_docs": None,
            "team_id": 1,
        }
        result = await self._node()(state)
        assert "Skipped" in result["messages"][0]

    @pytest.mark.asyncio
    @patch("maru_lang.graph.ingest.nodes.try_activate", new_callable=AsyncMock)
    @patch("maru_lang.graph.ingest.nodes.Document")
    @patch("maru_lang.graph.ingest.nodes.split_documents")
    @patch("maru_lang.graph.ingest.nodes.make_chunk_uid")
    async def test_process_splits_embeds_stores(
        self, mock_uid, mock_split, mock_doc_model, mock_try_activate
    ):
        from langchain_core.documents import Document as LCDoc
        from maru_lang.enums.documents import DocumentStatus

        mock_db_doc = MagicMock()
        mock_db_doc.status = DocumentStatus.PROCESSING  # not DELETING -> proceeds
        mock_doc_model.get_or_none = AsyncMock(return_value=mock_db_doc)
        mock_try_activate.return_value = True  # PROCESSING -> ACTIVE committed

        mock_vdb = MagicMock()
        mock_vdb.upsert_documents = MagicMock()
        mock_vdb.get_chunk_ids_by_document_id = MagicMock(return_value=[])

        mock_emb = MagicMock()
        mock_emb.embed_documents = MagicMock(return_value=[[0.1] * 384, [0.2] * 384])

        mock_split.return_value = [LCDoc(page_content="chunk1"), LCDoc(page_content="chunk2")]
        mock_uid.side_effect = lambda doc_id, idx, content: f"uid-{doc_id}-{idx}"

        state = {
            "document": {
                "id": 1, "name": "doc", "file_path": "/tmp/doc.txt",
                "storage_path": None, "group_id": 10, "metadata": {},
            },
            "needs_processing": True,
            "parsed_docs": [{"content": "test content", "metadata": {}}],
            "team_id": 1,
        }
        result = await self._node(mock_vdb, mock_emb)(state)

        assert result["total_chunks"] == 2
        assert "2 chunks" in result["messages"][0]
        mock_try_activate.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("maru_lang.graph.ingest.nodes.try_activate", new_callable=AsyncMock)
    @patch("maru_lang.graph.ingest.nodes.Document")
    @patch("maru_lang.graph.ingest.nodes.split_documents")
    @patch("maru_lang.graph.ingest.nodes.make_chunk_uid")
    async def test_process_cancels_when_delete_wins_commit(
        self, mock_uid, mock_split, mock_doc_model, mock_try_activate
    ):
        """try_activate False (delete marked DELETING mid-embed) -> cancel + cleanup."""
        from langchain_core.documents import Document as LCDoc
        from maru_lang.enums.documents import DocumentStatus

        processing_doc = MagicMock(); processing_doc.status = DocumentStatus.PROCESSING
        deleting_doc = MagicMock(); deleting_doc.status = DocumentStatus.DELETING
        deleting_doc.storage_path = None
        # 1st get_or_none: early guard (still PROCESSING) / 2nd: _finalize_cancel (DELETING)
        mock_doc_model.get_or_none = AsyncMock(side_effect=[processing_doc, deleting_doc])
        flt = MagicMock(); flt.delete = AsyncMock(return_value=1)
        mock_doc_model.filter = MagicMock(return_value=flt)
        mock_try_activate.return_value = False  # commit lost the race

        mock_vdb = MagicMock()
        mock_vdb.get_chunk_ids_by_document_id = MagicMock(return_value=[])
        mock_emb = MagicMock(); mock_emb.embed_documents = MagicMock(return_value=[[0.1] * 3])
        mock_split.return_value = [LCDoc(page_content="c1")]
        mock_uid.side_effect = lambda i, x, c: f"{i}-{x}"

        state = {
            "document": {"id": 1, "name": "doc", "file_path": "/tmp/doc.txt",
                         "storage_path": None, "group_id": 10, "metadata": {}},
            "needs_processing": True,
            "parsed_docs": [{"content": "x", "metadata": {}}],
            "team_id": 1,
        }
        result = await self._node(mock_vdb, mock_emb)(state)

        assert result["cancelled"] is True
        # chunks we wrote + the row are cleaned up
        mock_vdb.delete_all_chunks_by_document_id.assert_called_once_with(1)
        flt.delete.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("maru_lang.graph.ingest.nodes.try_activate", new_callable=AsyncMock)
    @patch("maru_lang.graph.ingest.nodes.Document")
    @patch("maru_lang.graph.ingest.nodes.split_documents")
    @patch("maru_lang.graph.ingest.nodes.make_chunk_uid")
    async def test_process_commit_race_to_active_leaves_doc_alone(
        self, mock_uid, mock_split, mock_doc_model, mock_try_activate
    ):
        """try_activate False인데 문서가 ACTIVE(중복 잡이 먼저 완료)면 청크/행을
        절대 건드리지 않는다 — 살아있는 문서를 지우면 안 됨."""
        from langchain_core.documents import Document as LCDoc
        from maru_lang.enums.documents import DocumentStatus

        processing_doc = MagicMock(); processing_doc.status = DocumentStatus.PROCESSING
        active_doc = MagicMock(); active_doc.status = DocumentStatus.ACTIVE
        mock_doc_model.get_or_none = AsyncMock(side_effect=[processing_doc, active_doc])
        flt = MagicMock(); flt.delete = AsyncMock(return_value=0)
        mock_doc_model.filter = MagicMock(return_value=flt)
        mock_try_activate.return_value = False

        mock_vdb = MagicMock()
        mock_vdb.get_chunk_ids_by_document_id = MagicMock(return_value=[])
        mock_emb = MagicMock(); mock_emb.embed_documents = MagicMock(return_value=[[0.1] * 3])
        mock_split.return_value = [LCDoc(page_content="c1")]
        mock_uid.side_effect = lambda i, x, c: f"{i}-{x}"

        state = {
            "document": {"id": 1, "name": "doc", "file_path": "/tmp/doc.txt",
                         "storage_path": None, "group_id": 10, "metadata": {}},
            "needs_processing": True,
            "parsed_docs": [{"content": "x", "metadata": {}}],
            "team_id": 1,
        }
        result = await self._node(mock_vdb, mock_emb)(state)

        assert result.get("skipped") is True
        assert result.get("cancelled") is not True
        mock_vdb.delete_all_chunks_by_document_id.assert_not_called()  # 청크 보존
        flt.delete.assert_not_awaited()  # 행 보존

    @pytest.mark.asyncio
    @patch("maru_lang.graph.ingest.nodes.Document")
    async def test_process_skips_when_deleting_before_embed(self, mock_doc_model):
        """Early DELETING guard: skip embedding entirely if delete already landed."""
        from maru_lang.enums.documents import DocumentStatus

        db_doc = MagicMock(); db_doc.status = DocumentStatus.DELETING
        mock_doc_model.get_or_none = AsyncMock(return_value=db_doc)
        flt = MagicMock(); flt.delete = AsyncMock(return_value=1)
        mock_doc_model.filter = MagicMock(return_value=flt)

        mock_emb = MagicMock(); mock_emb.embed_documents = MagicMock()
        mock_vdb = MagicMock()
        state = {
            "document": {"id": 1, "name": "doc", "file_path": "/tmp/d.txt",
                         "storage_path": None, "group_id": 1, "metadata": {}},
            "needs_processing": True,
            "parsed_docs": [{"content": "x", "metadata": {}}],
            "team_id": 1,
        }
        result = await self._node(mock_vdb, mock_emb)(state)

        assert result["cancelled"] is True
        mock_emb.embed_documents.assert_not_called()  # no wasted embedding


# ─── parse_document (mock parser+ORM) ────────────────────────


class TestParseDocument:
    @pytest.mark.asyncio
    async def test_skips_when_not_needed(self):
        from maru_lang.graph.ingest.nodes import parse_document

        state = {
            "document": {"id": 1, "name": "doc"},
            "needs_processing": False,
            "team_id": 1,
        }
        result = await parse_document(state)
        assert result["parsed_docs"] is None
        assert "Skipped" in result["messages"][0]

    @staticmethod
    def _doc_model_mock(db_doc):
        """Document mock whose get_or_none returns db_doc and filter().update() awaits."""
        m = MagicMock()
        m.get_or_none = AsyncMock(return_value=db_doc)
        flt = MagicMock()
        flt.update = AsyncMock(return_value=1)
        flt.delete = AsyncMock(return_value=1)
        m.filter = MagicMock(return_value=flt)
        m._filter = flt  # expose for assertions
        return m

    @pytest.mark.asyncio
    @patch("maru_lang.graph.ingest.nodes.begin_processing", new_callable=AsyncMock)
    @patch("maru_lang.graph.ingest.nodes.Document")
    @patch("maru_lang.graph.ingest.nodes.parse_file")
    async def test_parses_and_records_parser(
        self, mock_parse, mock_doc_model, mock_begin
    ):
        from maru_lang.graph.ingest.nodes import parse_document
        from langchain_core.documents import Document as LCDoc

        mock_db_doc = MagicMock()
        mock_db_doc.metadata = {}
        m = self._doc_model_mock(mock_db_doc)
        mock_doc_model.get_or_none = m.get_or_none
        mock_doc_model.filter = m.filter
        mock_begin.return_value = True  # claimed for processing

        mock_parse.return_value = ([LCDoc(page_content="parsed text")], "kordoc")

        state = {
            "document": {
                "id": 1, "name": "doc", "file_path": "/tmp/doc.pdf",
                "storage_path": None, "group_id": 10, "metadata": {},
            },
            "needs_processing": True,
            "team_id": 1,
        }
        result = await parse_document(state)

        assert result["parser"] == "kordoc"
        assert result["parsed_docs"] == [{"content": "parsed text", "metadata": {}}]
        # parser recorded via a field-scoped metadata update (not db_doc.save()).
        m._filter.update.assert_awaited_once_with(metadata={"parser": "kordoc"})

    @pytest.mark.asyncio
    @patch("maru_lang.graph.ingest.nodes.fail_processing", new_callable=AsyncMock)
    @patch("maru_lang.graph.ingest.nodes.begin_processing", new_callable=AsyncMock)
    @patch("maru_lang.graph.ingest.nodes.Document")
    @patch("maru_lang.graph.ingest.nodes.parse_file")
    async def test_parse_handles_empty_content(
        self, mock_parse, mock_doc_model, mock_begin, mock_fail
    ):
        from maru_lang.graph.ingest.nodes import parse_document

        mock_db_doc = MagicMock()
        mock_doc_model.get_or_none = AsyncMock(return_value=mock_db_doc)
        mock_begin.return_value = True
        mock_parse.return_value = ([], "langchain")

        state = {
            "document": {
                "id": 1, "name": "doc", "file_path": "/tmp/doc.txt",
                "storage_path": None, "group_id": 10, "metadata": {},
            },
            "needs_processing": True,
            "team_id": 1,
        }
        result = await parse_document(state)
        assert result["parsed_docs"] is None
        assert result["error"] == "Empty content"
        mock_fail.assert_awaited_once_with(1, "Empty content")

    @pytest.mark.asyncio
    @patch("maru_lang.graph.ingest.nodes.begin_processing", new_callable=AsyncMock)
    @patch("maru_lang.graph.ingest.nodes.Document")
    async def test_skips_when_delete_in_progress(self, mock_doc_model, mock_begin):
        """begin_processing False + status DELETING -> cancelled, no parse."""
        from maru_lang.graph.ingest.nodes import parse_document
        from maru_lang.enums.documents import DocumentStatus

        deleting_doc = MagicMock()
        deleting_doc.status = DocumentStatus.DELETING
        mock_doc_model.get_or_none = AsyncMock(return_value=deleting_doc)
        mock_begin.return_value = False

        state = {
            "document": {"id": 1, "name": "doc", "file_path": "/tmp/d.txt",
                         "storage_path": None, "group_id": 1, "metadata": {}},
            "needs_processing": True,
            "team_id": 1,
        }
        result = await parse_document(state)
        assert result["parsed_docs"] is None
        assert result["cancelled"] is True

    @pytest.mark.asyncio
    @patch("maru_lang.graph.ingest.nodes.begin_processing", new_callable=AsyncMock)
    @patch("maru_lang.graph.ingest.nodes.Document")
    async def test_claim_fail_on_active_is_skipped_not_cancelled(
        self, mock_doc_model, mock_begin
    ):
        """중복/스테일 잡: claim 실패했지만 DELETING이 아니면(예: ACTIVE) 절대
        cancelled로 처리하면 안 됨 — cancelled는 문서를 물리 삭제한다."""
        from maru_lang.graph.ingest.nodes import parse_document
        from maru_lang.enums.documents import DocumentStatus

        active_doc = MagicMock()
        active_doc.status = DocumentStatus.ACTIVE
        mock_doc_model.get_or_none = AsyncMock(return_value=active_doc)
        mock_begin.return_value = False

        state = {
            "document": {"id": 1, "name": "doc", "file_path": "/tmp/d.txt",
                         "storage_path": None, "group_id": 1, "metadata": {}},
            "needs_processing": True,
            "team_id": 1,
        }
        result = await parse_document(state)
        assert result.get("skipped") is True
        assert result.get("cancelled") is not True


# ─── Parser routing + KorDoc header strip ────────────────────


class TestParserRouting:
    @staticmethod
    def _set_config(**overrides):
        import maru_lang.configs.manager as mgr
        from maru_lang.configs.models import MaruConfig
        mgr._config = MaruConfig.from_dict(overrides)

    def test_disabled_routes_all_to_langchain(self):
        from maru_lang.graph.ingest.parser import select_parser
        from maru_lang.graph.ingest.constants import PARSER_LANGCHAIN
        self._set_config(kordoc_mcp_enabled=False)
        assert select_parser(".pdf", "d") == PARSER_LANGCHAIN
        assert select_parser(".txt", "d") == PARSER_LANGCHAIN

    def test_hwp_guard_when_disabled(self):
        from maru_lang.graph.ingest.parser import select_parser
        self._set_config(kordoc_mcp_enabled=False)
        with pytest.raises(ValueError, match="kordoc_mcp_enabled"):
            select_parser(".hwp", "d")

    def test_kordoc_only_when_enabled(self):
        from maru_lang.graph.ingest.parser import select_parser
        from maru_lang.graph.ingest.constants import PARSER_KORDOC
        self._set_config(kordoc_mcp_enabled=True)
        assert select_parser(".hwpx", "d") == PARSER_KORDOC

    def test_langchain_only_format_always_langchain(self):
        from maru_lang.graph.ingest.parser import select_parser
        from maru_lang.graph.ingest.constants import PARSER_LANGCHAIN
        self._set_config(kordoc_mcp_enabled=True)
        assert select_parser(".csv", "d") == PARSER_LANGCHAIN

    def test_dual_split_is_deterministic_and_balanced(self):
        from maru_lang.graph.ingest.parser import select_parser
        from maru_lang.graph.ingest.constants import PARSER_KORDOC
        self._set_config(kordoc_mcp_enabled=True, kordoc_mcp_ratio=0.5)
        assert select_parser(".pdf", "x") == select_parser(".pdf", "x")  # stable
        kc = sum(select_parser(".pdf", f"doc{i}") == PARSER_KORDOC for i in range(400))
        assert 120 < kc < 280  # roughly 50%, not all-or-nothing

    def test_ratio_zero_routes_dual_to_langchain(self):
        from maru_lang.graph.ingest.parser import select_parser
        from maru_lang.graph.ingest.constants import PARSER_LANGCHAIN
        self._set_config(kordoc_mcp_enabled=True, kordoc_mcp_ratio=0.0)
        assert all(
            select_parser(".docx", f"d{i}") == PARSER_LANGCHAIN for i in range(50)
        )

    def test_ingestible_extensions_follow_parser_config(self):
        """GET /config가 쓰는 목록: kordoc off면 hwp 계열 제외."""
        from maru_lang.graph.ingest.parser import ingestible_extensions
        self._set_config(kordoc_mcp_enabled=True)
        assert ".hwp" in ingestible_extensions()
        self._set_config(kordoc_mcp_enabled=False)
        exts = ingestible_extensions()
        assert ".hwp" not in exts and ".hwpx" not in exts
        assert ".pdf" in exts and ".md" in exts  # langchain 포맷은 유지

    def teardown_method(self):
        import maru_lang.configs.manager as mgr
        mgr._config = None  # don't leak injected config into other tests


class TestKordocHeaderStrip:
    def test_strips_meta_and_outline(self):
        from maru_lang.graph.ingest.loader.kordoc_mcp import _strip_header
        raw = "[포맷: DOCX]\n📑 문서 구조:\n- 제목\n\n# 본문\n\n내용"
        assert _strip_header(raw) == "# 본문\n\n내용"

    def test_meta_only(self):
        from maru_lang.graph.ingest.loader.kordoc_mcp import _strip_header
        assert _strip_header("[포맷: PDF]\n\n# 제목\n본문") == "# 제목\n본문"

    def test_passthrough_without_header(self):
        from maru_lang.graph.ingest.loader.kordoc_mcp import _strip_header
        assert _strip_header("plain body no header") == "plain body no header"


# ─── get_or_create_group_hierarchy (service; mock ORM) ───────


class TestGetOrCreateGroupHierarchy:
    @pytest.mark.asyncio
    @patch("maru_lang.services.document.get_or_create_document_group")
    async def test_creates_hierarchy_from_path(self, mock_get_or_create):
        from maru_lang.services.document import get_or_create_group_hierarchy

        call_count = 0
        async def side_effect(team_id, name, parent):
            nonlocal call_count
            call_count += 1
            group = MagicMock()
            group.id = call_count
            return group, True

        mock_get_or_create.side_effect = side_effect

        result = await get_or_create_group_hierarchy("/usr/local/data", team_id=1)
        assert result is not None
        assert call_count == 3  # usr, local, data

    @pytest.mark.asyncio
    @patch("maru_lang.services.document.get_or_create_document_group")
    async def test_skips_root_slash(self, mock_get_or_create):
        from maru_lang.services.document import get_or_create_group_hierarchy

        groups_created = []
        async def side_effect(team_id, name, parent):
            groups_created.append(name)
            group = MagicMock()
            return group, True

        mock_get_or_create.side_effect = side_effect

        await get_or_create_group_hierarchy("/data", team_id=1)
        assert "/" not in groups_created
