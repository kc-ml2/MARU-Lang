"""Document-authoring (doc) graph service — Canvas + CanvasVersion persistence.

Two layers:
  - DB ops (create_canvas/write_version/load_head/…): event-sourcing on whole-tree
    snapshots. Every applied edit appends an immutable CanvasVersion and moves the
    Canvas.head_version_id pointer. No per-block rows.
  - Pure tree helpers (set_block_text/add_block/delete_block/reorder_blocks/…):
    operate on a payload dict ({metadata, sections, blocks, missing_terms}) in
    place. The graph nodes deep-copy the head payload, apply one op, then persist
    it as the next version. LLM (re)generation is owned by the nodes.
"""
import copy
import uuid

from maru_lang.core.relation_db.models.auth import User, Team
from maru_lang.core.relation_db.models.chat import Session
from maru_lang.core.relation_db.models.canvas import Canvas, CanvasVersion
from maru_lang.enums.chat import CanvasStatus


def empty_payload() -> dict:
    """A blank canvas tree."""
    return {"metadata": {}, "sections": [], "missing_terms": []}


# --------------------------------------------------------------------------- #
# DB ops (event-sourcing)
# --------------------------------------------------------------------------- #
async def create_canvas(
    user: User,
    *,
    session: Session | None = None,
    team: Team | None = None,
    canvas_type: str | None = None,
    schema_version: str | None = None,
    title: str | None = None,
    instruction: str | None = None,
    references: list[dict] | None = None,
    metadata: dict | None = None,
) -> Canvas:
    """Create a new canvas (no versions yet) owned by ``user``."""
    return await Canvas.create(
        id=uuid.uuid4().hex,
        user=user,
        session=session,
        team=team,
        canvas_type=canvas_type,
        schema_version=schema_version,
        title=title,
        instruction=instruction,
        references=references or [],
        metadata=metadata or {},
    )


async def write_version(
    canvas: Canvas,
    payload: dict,
    *,
    base_version_id: str | None = None,
    op: dict | None = None,
) -> CanvasVersion:
    """Append an immutable snapshot and advance the canvas head pointer.

    ``base_version_id`` defaults to the current head (the version this one is
    derived from), forming the lineage. Touches Canvas.updated_at.
    """
    if base_version_id is None:
        base_version_id = canvas.head_version_id
    version = await CanvasVersion.create(
        id=uuid.uuid4().hex,
        canvas=canvas,
        base_version_id=base_version_id,
        op=op,
        payload=payload,
    )
    canvas.head_version_id = version.id
    await canvas.save()
    return version


async def get_canvas(canvas_id: str, *, user_id: int | None = None) -> Canvas | None:
    """Id lookup, optionally ownership-scoped.

    The doc graph passes the authenticated user_id so a caller can only ever
    touch a canvas they own (anyone knowing a canvas_id must still be its owner).
    user_id=None keeps the unscoped lookup for owner-agnostic callers (tooling).
    """
    if user_id is not None:
        return await Canvas.get_or_none(id=canvas_id, user_id=user_id)
    return await Canvas.get_or_none(id=canvas_id)


async def get_canvas_for_user(canvas_id: str, user: User) -> Canvas | None:
    """Ownership-checked lookup."""
    return await Canvas.get_or_none(id=canvas_id, user=user)


async def get_head_version(canvas: Canvas) -> CanvasVersion | None:
    """The canvas's current version (None if it has none yet)."""
    if not canvas.head_version_id:
        return None
    return await CanvasVersion.get_or_none(id=canvas.head_version_id)


async def load_head(
    canvas_id: str, *, user_id: int | None = None
) -> tuple[Canvas, CanvasVersion | None] | None:
    """Return a canvas and its head version (None if missing or not owned).

    When user_id is given the lookup is ownership-scoped, so the doc graph never
    reads or mutates a canvas belonging to another user.
    """
    canvas = await get_canvas(canvas_id, user_id=user_id)
    if canvas is None:
        return None
    return canvas, await get_head_version(canvas)


def list_versions(canvas: Canvas):
    """A canvas's version history as a QuerySet (oldest first)."""
    return CanvasVersion.filter(canvas=canvas).order_by("created_at")


async def set_status(canvas: Canvas, status: CanvasStatus) -> None:
    canvas.status = status
    await canvas.save()


async def finalize_canvas(canvas: Canvas) -> Canvas:
    """Mark a canvas FINALIZED (locked)."""
    canvas.status = CanvasStatus.FINALIZED
    await canvas.save()
    return canvas


def list_canvases_by_user(user: User):
    """User's canvases as a QuerySet (newest first; for pagination)."""
    return Canvas.filter(user=user).order_by("-updated_at")


def list_canvases_by_session(session_id: str):
    """A session's canvases as a QuerySet (newest first)."""
    return Canvas.filter(session_id=session_id).order_by("-updated_at")


def serialize_canvas(canvas: Canvas, version: CanvasVersion | None) -> dict:
    """Merge envelope (columns) + payload (version JSON) into the client shape."""
    payload = (version.payload if version else None) or empty_payload()
    return {
        "schema_version": canvas.schema_version,
        "canvas_type": canvas.canvas_type,
        "canvas_id": canvas.id,
        "version_id": version.id if version else None,
        "base_version_id": version.base_version_id if version else None,
        "status": canvas.status.name.lower(),
        "title": canvas.title,
        "metadata": payload.get("metadata", {}),
        "sections": payload.get("sections", []),
        "missing_terms": payload.get("missing_terms", []),
    }


# --------------------------------------------------------------------------- #
# Pure tree helpers (operate on a payload dict in place)
# --------------------------------------------------------------------------- #
def iter_blocks(payload: dict):
    """Yield (section, block) pairs across all sections in document order."""
    for section in payload.get("sections", []):
        for block in section.get("blocks", []):
            yield section, block


def find_block(payload: dict, block_id: str) -> tuple[dict | None, dict | None]:
    """Return (section, block) for ``block_id``, or (None, None) if absent."""
    for section, block in iter_blocks(payload):
        if block.get("block_id") == block_id:
            return section, block
    return None, None


def assign_ids(payload: dict) -> dict:
    """Fill section_id/block_id/order on an LLM-produced tree (mutates + returns).

    Sections become sec_001, sec_002, …; blocks blk_<sec>_<n>. Ids the model may
    already have set are overwritten so addressing is deterministic per draft.
    """
    for s_idx, section in enumerate(payload.get("sections", []), start=1):
        section["section_id"] = f"sec_{s_idx:03d}"
        section.setdefault("section_type", "article")
        section["order"] = s_idx
        section.setdefault("metadata", {})
        for b_idx, block in enumerate(section.get("blocks", []) or [], start=1):
            block["block_id"] = f"blk_{s_idx:03d}_{b_idx:03d}"
            block.setdefault("block_type", "paragraph")
            block.setdefault("meta_data", {})
            block.setdefault("source_refs", [])
    payload.setdefault("metadata", {})
    payload.setdefault("missing_terms", [])
    return payload


def _next_block_id(section: dict) -> str:
    """A fresh block_id within a section (sec id + an unused counter)."""
    sec_id = section.get("section_id", "sec_000")
    suffix = sec_id.split("_")[-1]
    used = {b.get("block_id") for b in section.get("blocks", [])}
    n = len(section.get("blocks", [])) + 1
    while f"blk_{suffix}_{n:03d}" in used:
        n += 1
    return f"blk_{suffix}_{n:03d}"


def set_block_text(
    payload: dict, block_id: str, text: str, *, source_refs: list | None = None
) -> bool:
    """Replace one block's text (block-level edit). Returns False if not found."""
    _, block = find_block(payload, block_id)
    if block is None:
        return False
    block["text"] = text
    if source_refs is not None:
        block["source_refs"] = source_refs
    return True


def add_block(
    payload: dict,
    *,
    block: dict,
    after_block_id: str | None = None,
    section_id: str | None = None,
) -> str | None:
    """Insert ``block`` after ``after_block_id`` (or at the end of its section).

    Target section is the one holding ``after_block_id``; else ``section_id``;
    else the last section. Returns the new block_id, or None if no section exists.
    """
    sections = payload.get("sections", [])
    if not sections:
        return None

    target_section = None
    insert_at = None
    if after_block_id is not None:
        for section in sections:
            blocks = section.get("blocks", [])
            for i, b in enumerate(blocks):
                if b.get("block_id") == after_block_id:
                    target_section, insert_at = section, i + 1
                    break
            if target_section is not None:
                break
    if target_section is None and section_id is not None:
        target_section = next((s for s in sections if s.get("section_id") == section_id), None)
    if target_section is None:
        target_section = sections[-1]

    new_block = dict(block)
    new_block["block_id"] = _next_block_id(target_section)
    new_block.setdefault("block_type", "paragraph")
    new_block.setdefault("meta_data", {})
    new_block.setdefault("source_refs", [])
    blocks = target_section.setdefault("blocks", [])
    if insert_at is None:
        insert_at = len(blocks)
    blocks.insert(insert_at, new_block)
    return new_block["block_id"]


def delete_block(payload: dict, block_id: str) -> bool:
    """Remove a block from its section. Returns False if not found."""
    for section in payload.get("sections", []):
        blocks = section.get("blocks", [])
        for i, b in enumerate(blocks):
            if b.get("block_id") == block_id:
                del blocks[i]
                return True
    return False


def reorder_blocks(
    payload: dict, ordered_ids: list[str], *, section_id: str | None = None
) -> bool:
    """Reorder blocks within a section to follow ``ordered_ids``.

    The section is ``section_id`` if given, else the one holding the first id.
    Ids not listed keep their relative order after the listed ones (never dropped).
    """
    sections = payload.get("sections", [])
    section = None
    if section_id is not None:
        section = next((s for s in sections if s.get("section_id") == section_id), None)
    elif ordered_ids:
        section, _ = find_block(payload, ordered_ids[0])
    if section is None:
        return False

    blocks = section.get("blocks", [])
    by_id = {b.get("block_id"): b for b in blocks}
    listed = [by_id[i] for i in ordered_ids if i in by_id]
    rest = [b for b in blocks if b.get("block_id") not in set(ordered_ids)]
    section["blocks"] = listed + rest
    return True


def index_references(references: list[dict]) -> dict[str, dict]:
    """Map chunk_id → reference dict for source-ref validation/enrichment."""
    return {str(r["chunk_id"]): r for r in references if r.get("chunk_id") is not None}
