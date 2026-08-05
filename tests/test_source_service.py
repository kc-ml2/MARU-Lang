"""DocumentSource-specific ingest and path hierarchy tests."""

from pathlib import Path

from maru_lang.core.relation_db.models.auth import Team, User
from maru_lang.core.relation_db.models.documents import Document, DocumentGroup
from maru_lang.enums.documents import DocumentStatus
from maru_lang.services.document import (
    get_or_create_relative_group_hierarchy,
    upsert_document_from_file,
)


async def _root_group() -> DocumentGroup:
    manager = await User.create(name="source-manager", email="source@example.com")
    team = await Team.create(name="source-team", manager=manager, is_private=True)
    return await DocumentGroup.create(name="source-root", team=team)


async def test_restored_inactive_file_is_scheduled_for_ingest(tmp_path: Path):
    """A restored same-version file must not remain permanently INACTIVE."""
    group = await _root_group()
    path = str(tmp_path / "restored.txt")

    doc, _, _ = await upsert_document_from_file(
        group=group,
        name="restored",
        path=path,
        size=9,
        mtime_ns=100,
    )
    doc.status = DocumentStatus.INACTIVE
    await doc.save()

    restored, needs_processing, action = await upsert_document_from_file(
        group=group,
        name="restored",
        path=path,
        size=9,
        mtime_ns=100,
    )

    assert restored.id == doc.id
    assert needs_processing is True
    assert action == "restored"
    assert restored.status == DocumentStatus.UPLOADING


async def test_same_size_new_mtime_is_detected_as_update(tmp_path: Path):
    """Fingerprint comparison detects edits whose byte size did not change."""
    group = await _root_group()
    path = str(tmp_path / "edited.txt")

    doc, _, _ = await upsert_document_from_file(
        group=group,
        name="edited",
        path=path,
        size=10,
        mtime_ns=100,
    )
    doc.status = DocumentStatus.ACTIVE
    await doc.save()
    old_fingerprint = doc.source_fingerprint

    updated, needs_processing, action = await upsert_document_from_file(
        group=group,
        name="edited",
        path=path,
        size=10,
        mtime_ns=200,
    )

    assert updated.id == doc.id
    assert needs_processing is True
    assert action == "updated"
    assert updated.status == DocumentStatus.UPLOADING
    assert updated.source_fingerprint != old_fingerprint


async def test_relative_hierarchy_does_not_duplicate_last_directory():
    root = await _root_group()

    group = await get_or_create_relative_group_hierarchy(
        root,
        "guides/api/document.pdf",
    )

    assert group.name == "api"
    assert (await group.parent).name == "guides"
    assert await DocumentGroup.filter(parent=group, name="api").count() == 0
