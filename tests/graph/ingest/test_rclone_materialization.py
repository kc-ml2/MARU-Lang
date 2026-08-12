from pathlib import Path
from subprocess import CompletedProcess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from maru_lang.graph.ingest.materialization import materialize_file
from maru_lang.graph.ingest.materialization.rclone import (
    _rclone_remote_path,
    resolve_rclone_materialization,
)


def test_remote_path_preserves_remote_base_and_relative_path(tmp_path):
    mount = tmp_path / "drive"
    source = mount / "folder" / "deck.pptx"
    source.parent.mkdir(parents=True)
    source.touch()

    with patch(
        "maru_lang.graph.ingest.materialization.rclone._mount_from_findmnt",
        return_value=("gdrive:shared", mount),
    ):
        assert _rclone_remote_path(source) == "gdrive:shared/folder/deck.pptx"


def _config(*, config_path=None, mounts=()):
    return SimpleNamespace(
        ingest_materialization=SimpleNamespace(
            rclone=SimpleNamespace(config_path=config_path, mounts=list(mounts))
        )
    )


def test_non_empty_file_does_not_match_rclone_provider(tmp_path):
    source = tmp_path / "report.docx"
    source.write_bytes(b"docx-content")

    with patch("maru_lang.graph.ingest.materialization.rclone._rclone_remote_path") as remote:
        assert resolve_rclone_materialization(source) is None
        remote.assert_not_called()


def test_configured_mount_uses_longest_matching_mapping(tmp_path):
    parent = tmp_path / "drive"
    nested = parent / "shared"
    source = nested / "folder" / "deck.pptx"
    source.parent.mkdir(parents=True)
    source.touch()
    mounts = [
        SimpleNamespace(local_path=str(parent), remote="drive:"),
        SimpleNamespace(local_path=str(nested), remote="shared:"),
    ]

    with patch(
        "maru_lang.graph.ingest.materialization.rclone.get_config",
        return_value=_config(mounts=mounts),
    ):
        assert _rclone_remote_path(source) == "shared:folder/deck.pptx"


def test_zero_byte_rclone_file_is_downloaded_and_cleaned_up(tmp_path):
    source = tmp_path / "slides.pptx"
    source.touch()
    materialized = None

    def fake_run(command, **kwargs):
        destination = Path(command[-1])
        destination.write_bytes(b"exported-pptx")
        return CompletedProcess(command, 0, stdout="", stderr="")

    with (
        patch(
            "maru_lang.graph.ingest.materialization.rclone._rclone_remote_path",
            return_value="drive:slides.pptx",
        ),
        patch(
            "maru_lang.graph.ingest.materialization.rclone.shutil.which",
            return_value="/usr/bin/rclone",
        ),
        patch(
            "maru_lang.graph.ingest.materialization.rclone.subprocess.run",
            side_effect=fake_run,
        ) as run,
    ):
        with materialize_file(source, resolvers=(resolve_rclone_materialization,)) as readable:
            materialized = readable
            assert readable != source
            assert readable.name == source.name
            assert readable.read_bytes() == b"exported-pptx"

    assert materialized is not None
    assert not materialized.parent.exists()
    assert run.call_args.args[0][:3] == ["rclone", "copyto", "drive:slides.pptx"]


def test_custom_rclone_config_is_passed_to_copyto(tmp_path):
    source = tmp_path / "slides.pptx"
    source.touch()

    def fake_run(command, **kwargs):
        Path(command[-1]).write_bytes(b"exported-pptx")
        return CompletedProcess(command, 0, stdout="", stderr="")

    with (
        patch(
            "maru_lang.graph.ingest.materialization.rclone._rclone_remote_path",
            return_value="drive:slides.pptx",
        ),
        patch(
            "maru_lang.graph.ingest.materialization.rclone.get_config",
            return_value=_config(config_path="/etc/rclone.conf"),
        ),
        patch(
            "maru_lang.graph.ingest.materialization.rclone.shutil.which",
            return_value="/usr/bin/rclone",
        ),
        patch(
            "maru_lang.graph.ingest.materialization.rclone.subprocess.run",
            side_effect=fake_run,
        ) as run,
    ):
        with materialize_file(source, resolvers=(resolve_rclone_materialization,)):
            pass

    assert run.call_args.args[0][:5] == [
        "rclone", "--config", "/etc/rclone.conf", "copyto", "drive:slides.pptx"
    ]


def test_detection_failure_points_to_mount_config(tmp_path):
    source = tmp_path / "slides.pptx"
    source.touch()

    with patch(
        "maru_lang.graph.ingest.materialization.rclone._rclone_remote_path",
        return_value=None,
    ):
        with pytest.raises(RuntimeError, match="ingest_materialization.rclone.mounts"):
            resolve_rclone_materialization(source)


def test_failed_rclone_download_has_useful_error_and_cleans_up(tmp_path):
    source = tmp_path / "doc.docx"
    source.touch()

    with (
        patch(
            "maru_lang.graph.ingest.materialization.rclone._rclone_remote_path",
            return_value="drive:doc.docx",
        ),
        patch(
            "maru_lang.graph.ingest.materialization.rclone.shutil.which",
            return_value="/usr/bin/rclone",
        ),
        patch(
            "maru_lang.graph.ingest.materialization.rclone.subprocess.run",
            return_value=CompletedProcess([], 1, stdout="", stderr="permission denied"),
        ),
    ):
        with pytest.raises(RuntimeError, match="permission denied"):
            with materialize_file(source, resolvers=(resolve_rclone_materialization,)):
                pass


def test_zero_byte_non_export_format_does_not_probe_rclone_mount(tmp_path):
    source = tmp_path / "empty.txt"
    source.touch()

    with patch(
        "maru_lang.graph.ingest.materialization.rclone._rclone_remote_path"
    ) as remote_path:
        assert resolve_rclone_materialization(source) is None
        remote_path.assert_not_called()
