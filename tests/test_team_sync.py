import os
import time
from types import SimpleNamespace

from maru_lang.core.relation_db.models.auth import Team, User
from maru_lang.core.relation_db.models.documents import Document, SourceStorage, TeamStorageLink
from maru_lang.enums.documents import DocumentStatus
from maru_lang.services import team_sync
from maru_lang.utils import file_storage


def _configure(monkeypatch, tmp_path, stable=0):
    cfg = SimpleNamespace(
        team_storage=SimpleNamespace(
            base_path=str(tmp_path / "teams"),
            stable_for_seconds=stable,
            scan_interval_seconds=0,
        ),
        storage_dir=str(tmp_path / "snapshots"),
    )
    monkeypatch.setattr(team_sync, "get_config", lambda: cfg)
    monkeypatch.setattr(file_storage, "get_config", lambda: cfg)
    return cfg


async def _team(tmp_path, monkeypatch):
    _configure(monkeypatch, tmp_path)
    owner = await User.create(name="owner", email="owner@sync.test")
    team = await Team.create(name="Sync Team", manager=owner)
    storage = await SourceStorage.create(id=f"storage-{team.id}", name="Sync", owner_team=team)
    await TeamStorageLink.create(team=team, storage=storage)
    source_dir = file_storage.provision_source_storage(storage.id)
    return team, source_dir


async def test_sync_discovers_snapshots_and_enqueues(tmp_path, monkeypatch):
    team, source_dir = await _team(tmp_path, monkeypatch)
    (source_dir / "folder").mkdir()
    source = source_dir / "folder" / "guide.md"
    source.write_text("first", encoding="utf-8")

    queued = []

    async def enqueue(doc_id, team_id):
        queued.append((doc_id, team_id))

    result = await team_sync.sync_team_folder(team.id, enqueue=enqueue)
    assert result.discovered == 1
    assert result.queued == 1
    assert len(queued) == 1

    doc = await Document.get(id=queued[0][0])
    assert doc.file_path == "folder/guide.md"
    assert doc.status == DocumentStatus.UPLOADING
    assert doc.metadata["source"] == "team_storage"
    assert doc.storage_path is None
    assert (source_dir / doc.file_path).read_text(encoding="utf-8") == "first"

    result = await team_sync.sync_team_folder(team.id, enqueue=enqueue)
    assert result.unchanged == 1
    assert result.queued == 0


async def test_sync_changed_terminal_document_reuses_identity(tmp_path, monkeypatch):
    team, source_dir = await _team(tmp_path, monkeypatch)
    source = source_dir / "guide.md"
    source.write_text("one", encoding="utf-8")
    first = await team_sync.sync_team_folder(team.id)
    assert first.queued == 1
    doc = await Document.get(file_path="guide.md")
    original_id = doc.id
    doc.status = DocumentStatus.ACTIVE
    await doc.save()

    source.write_text("two", encoding="utf-8")
    changed_at = time.time_ns()
    os.utime(source, ns=(changed_at, changed_at))
    second = await team_sync.sync_team_folder(team.id, now=time.time() + 1)
    assert second.queued == 1
    changed = await Document.get(id=original_id)
    assert changed.status == DocumentStatus.UPLOADING
    assert changed.storage_path is None
    assert (source_dir / changed.file_path).read_text(encoding="utf-8") == "two"


async def test_sync_defers_recent_and_inflight_changes(tmp_path, monkeypatch):
    _configure(monkeypatch, tmp_path, stable=30)
    owner = await User.create(name="owner", email="recent@sync.test")
    team = await Team.create(name="Recent", manager=owner)
    storage = await SourceStorage.create(id=f"storage-{team.id}", name="Recent", owner_team=team)
    await TeamStorageLink.create(team=team, storage=storage)
    source_dir = file_storage.provision_source_storage(storage.id)
    source = source_dir / "recent.md"
    source.write_text("new", encoding="utf-8")

    recent = await team_sync.sync_team_folder(team.id, now=time.time())
    assert recent.unstable == 1
    assert recent.queued == 0

    old = time.time() - 60
    os.utime(source, (old, old))
    await team_sync.sync_team_folder(team.id, now=time.time())
    doc = await Document.get(file_path="recent.md")
    source.write_text("changed while queued", encoding="utf-8")
    os.utime(source, (old, old))
    inflight = await team_sync.sync_team_folder(team.id, now=time.time())
    assert inflight.unstable == 1
    assert inflight.queued == 0
    assert (await Document.get(id=doc.id)).status == DocumentStatus.UPLOADING


async def test_sync_deletes_missing_managed_terminal_document(tmp_path, monkeypatch):
    team, source_dir = await _team(tmp_path, monkeypatch)
    source = source_dir / "gone.md"
    source.write_text("bye", encoding="utf-8")
    await team_sync.sync_team_folder(team.id)
    doc = await Document.get(file_path="gone.md")
    doc.status = DocumentStatus.ACTIVE
    await doc.save()
    source.unlink()

    async def delete_row(doc_id):
        await Document.filter(id=doc_id).delete()

    monkeypatch.setattr(team_sync, "finalize_document_deletion", delete_row)
    result = await team_sync.sync_team_folder(team.id)
    assert result.deleted == 1
    assert await Document.get_or_none(id=doc.id) is None
