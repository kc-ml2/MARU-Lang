"""VectorDB factory tests — URL parsing + embedded/server (HTTP) routing.

Run: venv/bin/python -m pytest tests/test_vector_db_factory.py -v
"""
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# Bypass maru_lang.__init__ full app loading (same shim as the other unit tests).
if "maru_lang" not in sys.modules:
    _fake = types.ModuleType("maru_lang")
    _fake.__path__ = ["maru_lang"]
    sys.modules["maru_lang"] = _fake

from maru_lang.core.vector_db.factory import get_vector_db, _parse_url, _parse_host_port


class TestUrlParsing:
    def test_embedded(self):
        assert _parse_url("chroma://data/chroma/maru") == ("chroma", "data/chroma", "maru")

    def test_http(self):
        assert _parse_url("chroma+http://localhost:8000/maru") == (
            "chroma+http", "localhost:8000", "maru",
        )

    def test_https(self):
        assert _parse_url("chroma+https://h.internal:8000/c") == (
            "chroma+https", "h.internal:8000", "c",
        )

    def test_host_port(self):
        assert _parse_host_port("localhost:9000") == ("localhost", 9000)
        assert _parse_host_port("myhost") == ("myhost", 8000)  # default port

    def test_no_scheme_raises(self):
        with pytest.raises(ValueError):
            _parse_url("data/chroma/maru")


def _patched_chromadb():
    """Patch the chromadb module used by ChromaVectorDB to avoid real clients."""
    cdb = MagicMock()
    col = MagicMock()
    col.metadata = {"hnsw:space": "cosine"}
    cdb.PersistentClient.return_value.get_or_create_collection.return_value = col
    cdb.HttpClient.return_value.get_or_create_collection.return_value = col
    return patch("maru_lang.core.vector_db.chroma.chromadb", cdb), cdb


class TestFactoryRouting:
    def test_embedded_uses_persistent_client(self):
        p, cdb = _patched_chromadb()
        with p:
            vdb = get_vector_db("chroma://data/chroma/maru")
        cdb.PersistentClient.assert_called_once()
        cdb.HttpClient.assert_not_called()
        assert vdb.persist_dir is not None  # absolute local path

    def test_http_uses_http_client(self):
        p, cdb = _patched_chromadb()
        with p:
            vdb = get_vector_db("chroma+http://myhost:9000/coll")
        cdb.HttpClient.assert_called_once_with(host="myhost", port=9000, ssl=False)
        cdb.PersistentClient.assert_not_called()
        assert vdb.persist_dir is None  # server mode owns the store

    def test_https_sets_ssl(self):
        p, cdb = _patched_chromadb()
        with p:
            get_vector_db("chroma+https://secure:8000/coll")
        cdb.HttpClient.assert_called_once_with(host="secure", port=8000, ssl=True)

    def test_default_port(self):
        p, cdb = _patched_chromadb()
        with p:
            get_vector_db("chroma+http://barehost/coll")
        cdb.HttpClient.assert_called_once_with(host="barehost", port=8000, ssl=False)

    def test_unsupported_scheme_raises(self):
        with pytest.raises(ValueError, match="Unsupported vector_db scheme"):
            get_vector_db("lance://data/lance/maru")
