from pathlib import Path

import pytest

from maru_lang.graph.ingest.materialization import Materialization, materialize_file


def test_unmatched_file_is_yielded_unchanged(tmp_path):
    source = tmp_path / "report.docx"
    source.write_bytes(b"original")

    with materialize_file(source, resolvers=()) as readable:
        assert readable == source.resolve()
        assert readable.read_bytes() == b"original"


def test_custom_resolver_can_apply_any_action_and_temp_file_is_cleaned(tmp_path):
    source = tmp_path / "placeholder.bin"
    source.touch()
    materialized = None

    def resolve(path: Path):
        if path.suffix != ".bin":
            return None
        return Materialization(
            provider="example",
            write_to=lambda destination: destination.write_bytes(b"resolved content"),
        )

    with materialize_file(source, resolvers=(resolve,)) as readable:
        materialized = readable
        assert readable.name == source.name
        assert readable.read_bytes() == b"resolved content"

    assert materialized is not None
    assert not materialized.parent.exists()


def test_first_matching_resolver_wins(tmp_path):
    source = tmp_path / "stub"
    source.touch()
    calls = []

    def first(path: Path):
        calls.append("first")
        return Materialization("first", lambda destination: destination.write_text("first"))

    def second(path: Path):
        calls.append("second")
        return Materialization("second", lambda destination: destination.write_text("second"))

    with materialize_file(source, resolvers=(first, second)) as readable:
        assert readable.read_text() == "first"
    assert calls == ["first"]


def test_provider_validation_is_centralized_and_cleanup_still_runs(tmp_path):
    source = tmp_path / "stub"
    source.touch()
    destination_parent = None

    def resolve(path: Path):
        def write_empty(destination: Path):
            nonlocal destination_parent
            destination_parent = destination.parent
            destination.touch()

        return Materialization(
            provider="strict",
            write_to=write_empty,
            validate=lambda destination: destination.stat().st_size > 0,
        )

    with pytest.raises(RuntimeError, match="strict produced an invalid file"):
        with materialize_file(source, resolvers=(resolve,)):
            pass

    assert destination_parent is not None
    assert not destination_parent.exists()
