"""Tests for scan_directory — only ingestible files are collected.

Run: venv/bin/python -m pytest tests/test_file_scanner.py -v
"""
import sys
import types

# Bypass maru_lang.__init__ full app loading (same shim as test_ingest.py)
if "maru_lang" not in sys.modules:
    _fake = types.ModuleType("maru_lang")
    _fake.__path__ = ["maru_lang"]
    sys.modules["maru_lang"] = _fake

import pytest

from maru_lang.utils.file_scanner import scan_directory


@pytest.fixture
def tree(tmp_path):
    for rel in [
        ".DS_Store", "a.md", "b.pdf", "c.exe", ".hidden.md",
        "sub/d.txt", "sub/e.bin", "졸업.hwpx",
    ]:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    return tmp_path


def test_keeps_only_supported_extensions(tree):
    names = {f.name for f in scan_directory(tree)}
    assert names == {"a.md", "b.pdf", "d.txt", "졸업.hwpx"}


def test_excludes_junk_and_unsupported(tree):
    names = {f.name for f in scan_directory(tree)}
    assert ".DS_Store" not in names      # macOS junk (no supported suffix)
    assert "c.exe" not in names          # unsupported
    assert "e.bin" not in names          # unsupported
    assert ".hidden.md" not in names     # dotfile skipped even if extension ok


def test_keeps_korean_doc_formats(tree):
    # hwp/hwpx are ingestible (via KorDoc) and must survive scanning.
    names = {f.name for f in scan_directory(tree)}
    assert "졸업.hwpx" in names


def test_non_recursive_skips_subdirs(tree):
    names = {f.name for f in scan_directory(tree, recursive=False)}
    assert "d.txt" not in names          # under sub/
    assert "a.md" in names


def test_missing_path_raises(tmp_path):
    with pytest.raises(ValueError):
        scan_directory(tmp_path / "nope")
