from pathlib import Path

import pytest

from maru_lang.utils import file_storage


def test_team_source_provision_and_atomic_upload(tmp_path, monkeypatch):
    from io import BytesIO
    from types import SimpleNamespace

    monkeypatch.setattr(
        file_storage,
        "get_config",
        lambda: SimpleNamespace(team_storage=SimpleNamespace(base_path=str(tmp_path))),
    )
    team_dir = file_storage.provision_team_storage(7, "영업 / Sales")
    assert team_dir == tmp_path / "7"

    stored = file_storage.save_team_source_upload(
        BytesIO(b"hello"), "report.txt", 7, "영업 / Sales", "quarterly"
    )
    assert stored.read_bytes() == b"hello"
    assert not list(stored.parent.glob("*.part"))


def test_team_source_folder_is_stable_when_team_name_changes(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        file_storage,
        "get_config",
        lambda: SimpleNamespace(team_storage=SimpleNamespace(base_path=str(tmp_path))),
    )
    assert file_storage.provision_team_storage(7, "Old Name") == tmp_path / "7"
    assert file_storage.provision_team_storage(7, "New Name") == tmp_path / "7"


def test_legacy_named_team_folder_is_migrated(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        file_storage,
        "get_config",
        lambda: SimpleNamespace(team_storage=SimpleNamespace(base_path=str(tmp_path))),
    )
    legacy = tmp_path / "7-Old-Name"
    legacy.mkdir()
    (legacy / "document.md").write_text("kept", encoding="utf-8")
    migrated = file_storage.provision_team_storage(7, "New Name")
    assert migrated == tmp_path / "7"
    assert (migrated / "document.md").read_text(encoding="utf-8") == "kept"
    assert not legacy.exists()


def test_team_source_upload_rejects_path_traversal(tmp_path, monkeypatch):
    from io import BytesIO
    from types import SimpleNamespace

    monkeypatch.setattr(
        file_storage,
        "get_config",
        lambda: SimpleNamespace(team_storage=SimpleNamespace(base_path=str(tmp_path))),
    )
    with pytest.raises(ValueError, match="잘못된 팀 파일 경로"):
        file_storage.save_team_source_upload(
            BytesIO(b"bad"), "escape.txt", 7, "sales", "../outside"
        )


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


