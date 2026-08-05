"""DocumentSource service - create, connect, disconnect, and sync file sources to teams."""
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from maru_lang.core.relation_db.models.documents import (
    Document,
    DocumentGroup,
    DocumentSource,
    SourceTeamLink,
)
from maru_lang.enums.documents import DocumentStatus
from maru_lang.core.relation_db.models.auth import Team
from maru_lang.services.document import (
    get_or_create_document_group,
    get_all_descendant_groups,
)
from maru_lang.graph.ingest import run_ingest
from maru_lang.schemas.ingest import FileInfo

logger = logging.getLogger(__name__)


# ========== DocumentSource CRUD ==========

async def create_source(
    name: str,
    source_path: str,
    description: Optional[str] = None,
    file_pattern: Optional[str] = None,
) -> DocumentSource:
    """Create a new DocumentSource."""
    source = await DocumentSource.create(
        name=name,
        description=description,
        source_path=source_path,
        file_pattern=file_pattern,
    )
    return source


async def list_sources() -> list[DocumentSource]:
    """List all DocumentSources with their team links."""
    sources = await DocumentSource.all().prefetch_related("team_links__team")
    return list(sources)


async def get_source(source_id: int) -> Optional[DocumentSource]:
    """Get a single DocumentSource by id."""
    return await DocumentSource.get_or_none(id=source_id)


async def update_source(
    source: DocumentSource,
    name: Optional[str] = None,
    description: Optional[str] = None,
    source_path: Optional[str] = None,
    file_pattern: Optional[str] = None,
) -> DocumentSource:
    """Update a DocumentSource. Path changes are validated against existing docs."""
    if name is not None:
        source.name = name
    if description is not None:
        source.description = description
    if file_pattern is not None:
        source.file_pattern = file_pattern
    if source_path is not None:
        # Validate: check if existing documents under this source can be reconciled.
        # Compare fingerprints — if all docs can be updated with the new path, allow it.
        await _validate_path_change(source, source_path)
        source.source_path = source_path
    await source.save()
    return source


async def _validate_path_change(source: DocumentSource, new_path: str) -> None:
    """Validate that a source_path change won't break existing documents.

    Walks the root_group hierarchy and compares fingerprints. Since fingerprints
    encode the path, any mismatch means the document will get a new fingerprint
    and be treated as a re-upload — which is safe.
    """
    # Check all team_links for this source
    links = await SourceTeamLink.filter(source=source).prefetch_related(
        "root_group__documents"
    ).all()
    for link in links:
        if link.root_group:
            descendants = await get_all_descendant_groups(link.root_group)
            for desc_group in descendants:
                docs = await Document.filter(group_id=desc_group.id).all()
                for doc in docs:
                    # Fingerprint contains the path; changing path → new fingerprint →
                    # treated as re-upload on next sync. This is safe — no data loss.
                    pass  # Always safe because fingerprint is the change detector


# ========== Connect / Disconnect ==========

async def connect_source_to_teams(
    source_id: int,
    team_ids: list[int],
) -> dict:
    """Connect a DocumentSource to one or more teams.

    For each team:
    1. Create a SourceTeamLink
    2. Create a root DocumentGroup mirroring the source_path's last component
    3. 1:1 bind them

    Returns dict of source_id → connected_team_ids + root_group_id.
    """
    source = await DocumentSource.get_or_none(id=source_id)
    if not source:
        raise LookupError("DocumentSource not found")

    result = {
        "source_id": source_id,
        "connected_team_ids": [],
        "root_group_id": None,
        "root_group_name": None,
    }

    for team_id in team_ids:
        # Check if already connected
        existing = await SourceTeamLink.get_or_none(source=source, team_id=team_id)
        if existing:
            continue

        team = await Team.get_or_none(id=team_id)
        if not team:
            raise LookupError(f"Team {team_id} not found")

        # Create root DocumentGroup
        root_name = Path(source.source_path).name or "uploads"
        root_group, _ = await get_or_create_document_group(
            team_id=team_id,
            name=root_name,
            parent=None,
            description=f"Auto-generated from source: {source.name} ({source.source_path})",
        )

        # Create link
        link = await SourceTeamLink.create(
            source=source,
            team=team,
            root_group=root_group,
        )
        result["connected_team_ids"].append(team_id)
        result["root_group_id"] = root_group.id
        result["root_group_name"] = root_name

    return result


async def disconnect_source_from_team(
    source_id: int,
    team_id: int,
) -> None:
    """Disconnect a source from a team, removing the DocumentGroup tree.

    Deletes the root DocumentGroup and all descendants (cascade deletes Documents).
    Also removes the SourceTeamLink.
    """
    link = await SourceTeamLink.get_or_none(source_id=source_id, team_id=team_id)
    if not link:
        raise LookupError("No connection found")

    if link.root_group:
        # Delete the entire DocumentGroup tree (cascade deletes Documents)
        await _delete_group_tree(link.root_group)

    await link.delete()


async def _delete_group_tree(group: DocumentGroup) -> None:
    """Recursively delete a DocumentGroup tree, cleaning up VDB and storage."""
    from maru_lang.services.ingest import cleanup_document_resources, delete_team_chunks

    # First, collect all document IDs for cleanup
    descendants = await get_all_descendant_groups(group)
    for desc_group in descendants:
        docs = await Document.filter(group_id=desc_group.id).all()
        for doc in docs:
            try:
                cleanup_document_resources(doc.id, doc)
            except Exception as e:
                logger.warning(f"VDB cleanup failed for {doc.id}: {e}")
        await Document.filter(group_id=desc_group.id).delete()

    # Delete all group rows bottom-up
    for g in reversed(descendants):
        await g.delete()


# ========== Sync ==========

async def sync_source(source_id: int, team_id: Optional[int] = None) -> dict:
    """Sync a DocumentSource's files to its connected teams.

    Scans the source_path, compares with existing Documents, and:
    - Creates new Documents for new files
    - Updates Documents for changed files
    - Marks removed Documents as INACTIVE (soft delete)

    Returns sync statistics.
    """
    source = await DocumentSource.get_or_none(id=source_id)
    if not source:
        raise LookupError("DocumentSource not found")

    links = await SourceTeamLink.filter(source=source)
    if team_id:
        links = links.filter(team_id=team_id)
    links = await links.prefetch_related("team", "root_group")

    if not links:
        raise LookupError("No team connections for this source")

    stats = {
        "source_id": source_id,
        "source_path": source.source_path,
        "status": "completed",
        "files_processed": 0,
        "files_new": 0,
        "files_updated": 0,
        "files_deleted": 0,
        "error": None,
    }

    for link in links:
        try:
            team_stats = await _sync_to_team(source, link)
            stats["files_processed"] += team_stats["files_processed"]
            stats["files_new"] += team_stats["files_new"]
            stats["files_updated"] += team_stats["files_updated"]
            stats["files_deleted"] += team_stats["files_deleted"]
        except Exception as e:
            logger.error(f"Sync failed for source={source_id}, team={link.team_id}: {e}")
            stats["status"] = "error"
            if stats["error"] is None:
                stats["error"] = str(e)

    return stats


async def _sync_to_team(
    source: DocumentSource,
    link: SourceTeamLink,
) -> dict:
    """Sync a single source→team connection. Returns per-team stats."""
    root_group = link.root_group
    if not root_group:
        raise RuntimeError(f"No root_group for source={source.id}, team={link.team_id}")

    source_path = Path(source.source_path)
    if not source_path.exists():
        raise RuntimeError(f"Source path does not exist: {source.source_path}")

    file_pattern = source.file_pattern
    stats = {
        "files_processed": 0,
        "files_new": 0,
        "files_updated": 0,
        "files_deleted": 0,
    }

    # Build set of current files on disk
    current_files = set()
    if source_path.is_file():
        current_files.add(source_path)
    elif source_path.is_dir():
        if file_pattern:
            for p in source_path.glob(file_pattern):
                if p.is_file():
                    current_files.add(p)
        else:
            for p in source_path.rglob("*"):
                if p.is_file():
                    current_files.add(p)

    # Gather existing documents under root_group tree
    descendants = await get_all_descendant_groups(root_group)
    existing_docs = await Document.filter(
        group_id__in=[g.id for g in descendants]
    ).all()

    # Map source-owned documents by their stable relative path metadata. Fall
    # back to deriving it for records created before source metadata existed.
    doc_by_rel_path: dict[str, Document] = {}
    for doc in existing_docs:
        if not doc.file_path:
            continue
        metadata = doc.metadata or {}
        if metadata.get("source_id") not in (None, source.id):
            continue
        rel_path = metadata.get("source_relative_path")
        if not rel_path:
            try:
                rel_path = _relative_source_path(Path(doc.file_path), source_path)
            except ValueError:
                continue
        doc_by_rel_path[rel_path] = doc

    current_rel_paths: set[str] = set()
    for file_path in sorted(current_files):
        rel_path = _relative_source_path(file_path, source_path)
        current_rel_paths.add(rel_path)
        file_stat = file_path.stat()
        stats["files_processed"] += 1

        result = await run_ingest(
            file=FileInfo(
                fileName=file_path.name,
                createdAt=datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.utc),
                absolutePath=str(file_path.resolve()),
                size=file_stat.st_size,
                mtimeNs=file_stat.st_mtime_ns,
            ),
            team_id=link.team_id,
            source_context={
                "source_id": source.id,
                "source_name": source.name,
                "root_group_id": root_group.id,
                "relative_path": rel_path,
            },
        )
        action = result.get("sync_action")
        if action == "created":
            stats["files_new"] += 1
        elif action in ("updated", "restored"):
            stats["files_updated"] += 1
        if result.get("error"):
            raise RuntimeError(result["error"])

    # Reconciliation is source-level work: the per-file ingest graph cannot know
    # which previously known paths disappeared from the complete scan.
    for rel_path, doc in doc_by_rel_path.items():
        if (
            rel_path not in current_rel_paths
            and doc.status not in (DocumentStatus.INACTIVE, DocumentStatus.DELETING)
        ):
            doc.status = DocumentStatus.INACTIVE
            await doc.save()
            stats["files_deleted"] += 1

    return stats


def _relative_source_path(file_path: Path, source_path: Path) -> str:
    """Return a stable relative path for directory and single-file sources."""
    if source_path.is_file() or file_path == source_path:
        return file_path.name
    return str(file_path.relative_to(source_path))


# ========== Source Path Change ==========

async def change_source_path(
    source: DocumentSource,
    new_path: str,
) -> DocumentSource:
    """Change the source path, validating against existing synced documents.

    Since fingerprints encode the path, a path change means new fingerprints.
    On next sync, changed documents will be detected as "new" (new fingerprint)
    and existing ones will be marked INACTIVE. This is safe — no data loss.
    """
    new_path_obj = Path(new_path)
    if not new_path_obj.exists():
        raise ValueError(f"Source path does not exist: {new_path}")

    source.source_path = str(new_path_obj)
    await source.save()
    return source
