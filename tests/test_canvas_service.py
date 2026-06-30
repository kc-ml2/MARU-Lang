"""Tests for the doc-graph canvas service (Canvas/CanvasVersion event-sourcing)."""
import copy

from maru_lang.enums.chat import CanvasStatus
from maru_lang.services.canvas import (
    add_block,
    assign_ids,
    create_canvas,
    delete_block,
    finalize_canvas,
    find_block,
    index_references,
    list_canvases_by_user,
    load_head,
    reorder_blocks,
    serialize_canvas,
    set_block_text,
    write_version,
)


def _tree(texts):
    """A one-section canvas tree with ids assigned (blk_001_001, …)."""
    return assign_ids({
        "metadata": {"title": "T"},
        "sections": [{
            "section_type": "article",
            "title": "S1",
            "metadata": {"article_no": "제1조"},
            "blocks": [
                {"block_type": "paragraph", "text": t, "source_refs": []} for t in texts
            ],
        }],
        "missing_terms": [],
    })


def _block_ids(tree):
    return [b["block_id"] for _s, b in
            [(s, b) for s in tree["sections"] for b in s["blocks"]]]


class TestTreeHelpers:
    """Pure payload-tree transforms (no DB)."""

    def test_assign_ids_is_deterministic(self):
        tree = _tree(["a", "b"])
        assert tree["sections"][0]["section_id"] == "sec_001"
        assert _block_ids(tree) == ["blk_001_001", "blk_001_002"]

    def test_find_block(self):
        tree = _tree(["a", "b"])
        section, block = find_block(tree, "blk_001_002")
        assert block["text"] == "b"
        assert section["section_id"] == "sec_001"
        assert find_block(tree, "ghost") == (None, None)

    def test_set_block_text_targets_one(self):
        tree = _tree(["a", "b"])
        assert set_block_text(tree, "blk_001_001", "A2") is True
        assert [b["text"] for _s, b in _iter(tree)] == ["A2", "b"]
        assert set_block_text(tree, "ghost", "x") is False

    def test_add_block_inserts_after(self):
        tree = _tree(["a", "b"])
        new_id = add_block(tree, block={"text": "mid"}, after_block_id="blk_001_001")
        texts = [b["text"] for _s, b in _iter(tree)]
        assert texts == ["a", "mid", "b"]
        assert new_id and new_id not in ("blk_001_001", "blk_001_002")

    def test_add_block_at_end_when_no_anchor(self):
        tree = _tree(["a", "b"])
        add_block(tree, block={"text": "end"}, after_block_id=None)
        assert [b["text"] for _s, b in _iter(tree)] == ["a", "b", "end"]

    def test_delete_block(self):
        tree = _tree(["a", "b", "c"])
        assert delete_block(tree, "blk_001_002") is True
        assert [b["text"] for _s, b in _iter(tree)] == ["a", "c"]
        assert delete_block(tree, "ghost") is False

    def test_reorder_within_section(self):
        tree = _tree(["a", "b", "c"])
        reorder_blocks(tree, ["blk_001_003", "blk_001_001", "blk_001_002"])
        assert [b["text"] for _s, b in _iter(tree)] == ["c", "a", "b"]

    def test_index_references(self):
        idx = index_references([{"chunk_id": "x", "document_name": "D"}])
        assert idx["x"]["document_name"] == "D"


class TestCanvasPersistence:
    async def test_write_version_advances_head(self, user_alice):
        canvas = await create_canvas(user_alice, canvas_type="contract")
        v1 = await write_version(canvas, _tree(["a"]), base_version_id=None)
        assert canvas.head_version_id == v1.id
        loaded_canvas, head = await load_head(canvas.id)
        assert head.id == v1.id
        assert head.payload["sections"][0]["blocks"][0]["text"] == "a"

    async def test_version_lineage(self, user_alice):
        canvas = await create_canvas(user_alice, canvas_type="contract")
        v1 = await write_version(canvas, _tree(["a"]))
        v2 = await write_version(canvas, _tree(["b"]))
        assert v1.base_version_id is None
        assert v2.base_version_id == v1.id     # chained to predecessor
        assert canvas.head_version_id == v2.id

    async def test_edit_then_new_version_is_isolated(self, user_alice):
        canvas = await create_canvas(user_alice, canvas_type="contract")
        v1 = await write_version(canvas, _tree(["a", "b"]))
        payload = copy.deepcopy(v1.payload)
        set_block_text(payload, "blk_001_002", "B-edited")
        await write_version(canvas, payload, base_version_id=v1.id)
        # v1 snapshot is immutable; head reflects the edit
        _, head = await load_head(canvas.id)
        assert head.payload["sections"][0]["blocks"][1]["text"] == "B-edited"
        from maru_lang.core.relation_db.models.canvas import CanvasVersion
        old = await CanvasVersion.get(id=v1.id)
        assert old.payload["sections"][0]["blocks"][1]["text"] == "b"

    async def test_finalize_sets_status(self, user_alice):
        canvas = await create_canvas(user_alice, canvas_type="contract")
        await write_version(canvas, _tree(["a"]))
        await finalize_canvas(canvas)
        from maru_lang.core.relation_db.models.canvas import Canvas
        assert (await Canvas.get(id=canvas.id)).status == CanvasStatus.FINALIZED

    async def test_list_canvases_by_user(self, user_alice):
        await create_canvas(user_alice, canvas_type="contract")
        await create_canvas(user_alice, canvas_type="email")
        assert await list_canvases_by_user(user_alice).count() == 2

    async def test_serialize_canvas_merges_envelope_and_payload(self, user_alice):
        canvas = await create_canvas(
            user_alice, canvas_type="contract", schema_version="contract.v1", title="계약서")
        v1 = await write_version(canvas, _tree(["a"]))
        out = serialize_canvas(canvas, v1)
        assert out["canvas_id"] == canvas.id
        assert out["version_id"] == v1.id
        assert out["canvas_type"] == "contract"
        assert out["schema_version"] == "contract.v1"
        assert out["status"] == "drafting"
        assert out["title"] == "계약서"
        assert out["sections"][0]["blocks"][0]["text"] == "a"


def _iter(tree):
    for s in tree["sections"]:
        for b in s["blocks"]:
            yield s, b
