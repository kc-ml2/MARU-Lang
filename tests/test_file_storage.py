from pathlib import Path

import pytest

from maru_lang.utils import file_storage


def test_remove_team_storage_removes_only_team_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(file_storage, "get_storage_dir", lambda: tmp_path)
    team_dir = tmp_path / "7"
    team_dir.mkdir()
    (team_dir / "document").write_text("stored", encoding="utf-8")
    unrelated = tmp_path / "8"
    unrelated.mkdir()

    assert file_storage.remove_team_storage(7) is True
    assert not team_dir.exists()
    assert unrelated.exists()


def test_remove_team_storage_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(file_storage, "get_storage_dir", lambda: tmp_path)

    assert file_storage.remove_team_storage(7) is False


def test_remove_team_storage_raises_on_symlink(tmp_path, monkeypatch):
    """심볼릭 링크로 위장한 경로는 절대 삭제하지 않는다."""
    monkeypatch.setattr(file_storage, "get_storage_dir", lambda: tmp_path)

    team_dir = tmp_path / "7"
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    team_dir.symlink_to(real_dir)

    with pytest.raises(ValueError, match="팀 저장소 경로가 디렉터리가 아닙니다"):
        file_storage.remove_team_storage(7)

    # 실제 대상 디렉토리는 살아있어야 한다
    assert real_dir.exists()


