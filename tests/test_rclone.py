from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from maru_lang.utils.rclone import _rclone_remote_path, materialize_rclone_file


def test_remote_path_preserves_remote_base_and_relative_path(tmp_path):
    mount = tmp_path / "drive"
    source = mount / "folder" / "deck.pptx"
    source.parent.mkdir(parents=True)
    source.touch()

    with patch("maru_lang.utils.rclone._mount_from_findmnt", return_value=("gdrive:shared", mount)):
        assert _rclone_remote_path(source) == "gdrive:shared/folder/deck.pptx"


def test_non_empty_file_is_used_without_rclone(tmp_path):
    source = tmp_path / "report.docx"
    source.write_bytes(b"docx-content")

    with patch("maru_lang.utils.rclone._rclone_remote_path") as remote:
        with materialize_rclone_file(source) as readable:
            assert readable == source.resolve()
            assert readable.read_bytes() == b"docx-content"
        remote.assert_not_called()


def test_zero_byte_rclone_file_is_downloaded_and_cleaned_up(tmp_path):
    source = tmp_path / "slides.pptx"
    source.touch()
    materialized = None

    def fake_run(command, **kwargs):
        destination = Path(command[-1])
        destination.write_bytes(b"exported-pptx")
        return CompletedProcess(command, 0, stdout="", stderr="")

    with (
        patch("maru_lang.utils.rclone._rclone_remote_path", return_value="drive:slides.pptx"),
        patch("maru_lang.utils.rclone.shutil.which", return_value="/usr/bin/rclone"),
        patch("maru_lang.utils.rclone.subprocess.run", side_effect=fake_run) as run,
    ):
        with materialize_rclone_file(source) as readable:
            materialized = readable
            assert readable != source
            assert readable.name == source.name
            assert readable.read_bytes() == b"exported-pptx"

    assert materialized is not None
    assert not materialized.parent.exists()
    assert run.call_args.args[0][:3] == ["rclone", "copyto", "drive:slides.pptx"]


def test_failed_rclone_download_has_useful_error_and_cleans_up(tmp_path):
    source = tmp_path / "doc.docx"
    source.touch()

    with (
        patch("maru_lang.utils.rclone._rclone_remote_path", return_value="drive:doc.docx"),
        patch("maru_lang.utils.rclone.shutil.which", return_value="/usr/bin/rclone"),
        patch(
            "maru_lang.utils.rclone.subprocess.run",
            return_value=CompletedProcess([], 1, stdout="", stderr="permission denied"),
        ),
    ):
        with pytest.raises(RuntimeError, match="permission denied"):
            with materialize_rclone_file(source):
                pass


def test_zero_byte_regular_file_remains_unchanged(tmp_path):
    source = tmp_path / "empty.txt"
    source.touch()

    with patch("maru_lang.utils.rclone._rclone_remote_path", return_value=None):
        with materialize_rclone_file(source) as readable:
            assert readable == source.resolve()
            assert readable.stat().st_size == 0
