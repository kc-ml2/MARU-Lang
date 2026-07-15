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
import re
import unicodedata
import uuid
from typing import TypedDict

from maru_lang.core.relation_db.models.auth import User, Team
from maru_lang.core.relation_db.models.chat import Session
from maru_lang.core.relation_db.models.canvas import Canvas, CanvasVersion
from maru_lang.enums.chat import CanvasStatus


class Party(TypedDict, total=False):
    """A contract party in metadata.parties. ``label`` (갑/을) is the match key for
    set_parties; the rest are filled in by the client's set_parties op."""
    label: str          # 갑 / 을 — stable identifier, set at draft time
    role: str           # client / vendor / …
    name: str           # 상호/성명 — blank until the client fills it
    address: str
    representative: str


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


# Party fields a set_parties op may fill (label is the match key, not overwritten).
_PARTY_FIELDS = ("name", "address", "representative", "role")


def set_parties(payload: dict, parties: list[Party]) -> bool:
    """Merge party info into metadata.parties, matched by ``label`` (e.g. 갑/을).

    Existing parties (seeded from the preset) are updated field-by-field; an
    incoming party whose label isn't present is appended. Returns True if anything
    changed, so the edit loop can skip a no-op version.
    """
    if not parties:
        return False
    meta = payload.setdefault("metadata", {})
    existing = meta.setdefault("parties", [])
    by_label = {p.get("label"): p for p in existing if p.get("label")}
    changed = False
    for incoming in parties:
        if not isinstance(incoming, dict):
            continue
        label = incoming.get("label")
        target = by_label.get(label)
        if target is None:
            if not label:
                continue  # can't match an unlabeled party to an existing one
            target = {"label": label}
            existing.append(target)
            by_label[label] = target
            changed = True
        for field in _PARTY_FIELDS:
            if field in incoming and incoming[field] != target.get(field):
                target[field] = incoming[field]
                changed = True
    return changed


def _term_token(label: str) -> str:
    """The canonical inline placeholder for an undetermined value: ``{{label}}``."""
    return "{{" + label + "}}"


def _term_tokens(label: str) -> list[str]:
    """Every placeholder spelling we accept for a term label.

    Canonically the draft writes ``{{label}}``, but the draft prompt is rendered
    with ``str.format()`` which collapses ``{{`` → ``{``, so real drafts have long
    emitted single-brace ``{label}`` too — accept both. Each brace form is offered
    in NFC and NFD to survive Hangul normalization drift. Double-brace variants
    come first so a ``{{x}}`` is consumed whole before its ``{x}`` substring can
    strand a stray brace.
    """
    label = unicodedata.normalize("NFC", label)
    tokens = []
    for tok in ("{{" + label + "}}", "{" + label + "}"):
        tokens.append(tok)
        nfd = unicodedata.normalize("NFD", tok)
        if nfd != tok:
            tokens.append(nfd)
    return tokens


# A placeholder token: one or two braces around a non-brace label — `{label}` or
# `{{label}}`. The draft LLM is asked for `{{label}}`, but since it can't be forced
# to, we accept either and canonicalize in code (see extract_terms).
_TERM_TOKEN_RE = re.compile(r"\{{1,2}([^{}]+?)\}{1,2}")


def extract_terms(payload: dict) -> dict:
    """Deterministically (re)build missing_terms from the placeholder tokens that
    actually appear in block text, and canonicalize every token to ``{{label}}``.

    This is the source of truth for undetermined values: rather than trusting the
    LLM to keep its inline tokens and its missing_terms list in sync (they drift —
    brace count, label spelling, forgotten entries), we scan the prose, take the
    tokens as authoritative, and derive the list from them. So token ↔ missing_term
    ↔ block_ids are 1:1 by construction, and set_terms later matches exactly.

    The LLM's own missing_terms is kept only to enrich each term's `description`.
    Labels are NFC-normalized (matches how the client will echo them). Mutates and
    returns payload.
    """
    # Descriptions the LLM proposed, keyed by NFC label (its list is advisory).
    prior_desc = {
        unicodedata.normalize("NFC", m["label"]): (m.get("description") or "")
        for m in (payload.get("missing_terms") or [])
        if isinstance(m, dict) and m.get("label")
    }

    order: list[str] = []
    block_ids: dict[str, list[str]] = {}

    for _section, block in iter_blocks(payload):
        bid = block.get("block_id")

        def _canon(match: "re.Match") -> str:
            label = unicodedata.normalize("NFC", match.group(1).strip())
            if label not in block_ids:
                block_ids[label] = []
                order.append(label)
            if bid and bid not in block_ids[label]:
                block_ids[label].append(bid)
            return "{{" + label + "}}"

        text = block.get("text") or ""
        canon = _TERM_TOKEN_RE.sub(_canon, text)
        if canon != text:
            block["text"] = canon

    payload["missing_terms"] = [
        {"label": label, "description": prior_desc.get(label, ""), "block_ids": block_ids[label]}
        for label in order
    ]
    return payload


def fill_terms(payload: dict, terms: list[dict]) -> bool:
    """Fill undetermined values into the doc and clear them from missing_terms.

    Each term is ``{label, value}``; the label matches a missing_term (and the
    ``{{label}}`` token the draft left in block text). Every occurrence of the
    token is replaced with the value, and the label is dropped from missing_terms
    (whether or not a token was present — the user resolved it). Mirrors set_parties
    but writes into block text, since term values live inline (not in metadata).
    Returns True if anything changed, so the edit loop can skip a no-op version.
    """
    if not terms:
        return False
    # Match by NFC-normalized label: the label round-trips draft JSON -> client
    # input -> resume, and a Unicode normalization drift (NFC vs NFD Hangul) would
    # otherwise make exact-string matching a silent no-op — no token replaced, no
    # missing_term dropped, so the client sees the canvas "not update" at all.
    values = {
        unicodedata.normalize("NFC", t["label"]): (t.get("value") or "")
        for t in terms
        if isinstance(t, dict) and t.get("label")
    }
    if not values:
        return False

    changed = False
    for label, value in values.items():
        # Accept every placeholder spelling ({{label}}/{label}, NFC/NFD): only the
        # token substring is rewritten, leaving the rest of the block byte-for-byte
        # intact. Double-brace forms are tried first so {{x}} is consumed whole.
        tokens = _term_tokens(label)
        for _section, block in iter_blocks(payload):
            text = block.get("text") or ""
            for token in tokens:
                if token in text:
                    text = text.replace(token, value)
                    changed = True
            block["text"] = text

    missing = payload.get("missing_terms") or []
    kept = [
        m for m in missing
        if unicodedata.normalize(
            "NFC", (m.get("label") if isinstance(m, dict) else m) or ""
        ) not in values
    ]
    if len(kept) != len(missing):
        payload["missing_terms"] = kept
        changed = True
    return changed


def index_references(references: list[dict]) -> dict[str, dict]:
    """Map chunk_id → reference dict for source-ref validation/enrichment."""
    return {str(r["chunk_id"]): r for r in references if r.get("chunk_id") is not None}
