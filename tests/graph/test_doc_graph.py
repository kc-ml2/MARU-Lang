"""Doc graph E2E — draft → interrupt → edits → finalize, with versioned persistence."""
import json

from unittest.mock import MagicMock, AsyncMock, patch
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langgraph.types import Command

from maru_lang.core.relation_db.models.auth import Team
from maru_lang.core.relation_db.models.canvas import Canvas, CanvasVersion
from maru_lang.core.relation_db.models.documents import Document as DocModel, DocumentGroup
from maru_lang.enums.chat import CanvasStatus
from maru_lang.enums.documents import DocumentStatus


# One section, two blocks. ghost-id is hallucinated → must be dropped on validate.
_CANVAS_JSON = json.dumps({
    "metadata": {"title": "용역계약서"},
    "sections": [{
        "section_type": "article",
        "title": "목적",
        "metadata": {"article_no": "제1조"},
        "blocks": [
            {"block_type": "paragraph", "text": "제1조 본문 A", "source_refs": ["chunk-1"]},
            {"block_type": "paragraph", "text": "제1조 본문 B",
             "source_refs": ["chunk-1", "ghost-id"]},
        ],
    }],
    "missing_terms": [{"label": "계약금액", "description": "미정"}],
})


def _mock_model():
    """Model returns the canvas tree for the draft prompt, plain text for edits."""
    model = MagicMock(spec=BaseChatModel)

    async def _ainvoke(messages, **_):
        text = messages[0].content if messages else ""
        if "분류" in text:           # DOC_CLASSIFY_PROMPT marker
            return AIMessage(content="contract")
        if "JSON 객체" in text:      # DOC_DRAFT_PROMPT marker
            return AIMessage(content=_CANVAS_JSON)
        return AIMessage(content="수정된 본문")
    model.ainvoke = AsyncMock(side_effect=_ainvoke)
    return model


def _mock_retriever():
    retriever = MagicMock()
    chunk = Document(id="chunk-1", page_content="표준 손해배상 조항",
                     metadata={"document_id": "d1", "document_name": "표준계약서", "score": 0.9})
    retriever.ainvoke = AsyncMock(return_value=[chunk])

    def _copy(update=None):
        c = MagicMock()
        c.ainvoke = retriever.ainvoke
        return c
    retriever.model_copy = MagicMock(side_effect=_copy)
    return retriever


def _mock_vdb(names=None):
    """Vector DB whose get_documents returns one chunk per requested document_id."""
    names = names or {}
    vdb = MagicMock()

    def _get(doc_ids):
        return [
            Document(id=f"{did}::0", page_content=f"{did} 표준 본문",
                     metadata={"document_id": did, "document_name": names.get(did, did)})
            for did in doc_ids
        ]
    vdb.get_documents = MagicMock(side_effect=_get)
    return vdb


def _build_graph(vdb=None):
    with patch("maru_lang.graph.doc.graph.build_retriever", return_value=_mock_retriever()), \
         patch("maru_lang.graph.doc.graph.build_compressor", return_value=None), \
         patch("maru_lang.graph.doc.graph.get_vector_db", return_value=vdb or MagicMock()):
        from maru_lang.graph.doc.graph import create_doc_graph
        return create_doc_graph(model=_mock_model())


async def _team_with_templates(user, names):
    """Create a team + ACTIVE template documents named `names` (id == name key)."""
    team = await Team.create(name="TplTeam", manager=user)
    group = await DocumentGroup.create(name="표준양식", team=team)
    for doc_id, doc_name in names.items():
        await DocModel.create(id=doc_id, name=doc_name, group=group,
                              status=DocumentStatus.ACTIVE)
    return team


def _cfg(tid):
    return {"configurable": {"thread_id": tid}}


async def _interrupt_value(graph, config):
    snap = await graph.aget_state(config)
    for task in snap.tasks:
        if task.interrupts:
            return task.interrupts[0].value
    return None


def _blocks(canvas_payload):
    return [b for s in canvas_payload.get("sections", []) for b in s.get("blocks", [])]


class TestDocGraph:
    async def test_new_canvas_persists_and_pauses(self, user_alice):
        graph = _build_graph()
        cfg = _cfg("doc-1")
        from maru_lang.graph.doc.state import build_doc_input
        await graph.ainvoke(
            build_doc_input("계약서 초안", [1], ["T"], user_id=user_alice.id, canvas_type="contract"),
            config=cfg,
        )
        # Canvas + first version persisted
        canvases = await Canvas.filter(user=user_alice)
        assert len(canvases) == 1
        canvas = canvases[0]
        # preset classified → deterministic type/schema persisted
        assert canvas.canvas_type == "contract"
        assert canvas.schema_version == "contract.v1"
        assert canvas.head_version_id is not None
        head = await CanvasVersion.get(id=canvas.head_version_id)
        blocks = head.payload["sections"][0]["blocks"]
        assert [b["text"] for b in blocks] == ["제1조 본문 A", "제1조 본문 B"]
        # hallucinated chunk id dropped, valid one kept + enriched
        assert [r["chunk_id"] for r in blocks[1]["source_refs"]] == ["chunk-1"]
        assert blocks[1]["source_refs"][0]["document_name"] == "표준계약서"
        # paused at await_edit, surfacing the whole canvas
        val = await _interrupt_value(graph, cfg)
        assert val["type"] == "awaiting_edit"
        assert val["canvas_id"] == canvas.id
        assert len(_blocks(val["canvas"])) == 2

    async def test_edit_op_regenerates_only_target_block(self, user_alice):
        graph = _build_graph()
        cfg = _cfg("doc-2")
        from maru_lang.graph.doc.state import build_doc_input
        await graph.ainvoke(
            build_doc_input("계약서", [1], ["T"], user_id=user_alice.id), config=cfg)
        val = await _interrupt_value(graph, cfg)
        target = _blocks(val["canvas"])[1]["block_id"]
        await graph.ainvoke(
            Command(resume={"op": "edit", "block_id": target, "feedback": "더 공식적으로"}),
            config=cfg)
        canvas = await Canvas.filter(user=user_alice).first()
        head = await CanvasVersion.get(id=canvas.head_version_id)
        blocks = head.payload["sections"][0]["blocks"]
        assert blocks[0]["text"] == "제1조 본문 A"     # untouched
        assert blocks[1]["text"] == "수정된 본문"        # regenerated
        # a new version was appended (lineage), not an in-place mutation
        assert head.base_version_id is not None
        assert await CanvasVersion.filter(canvas=canvas).count() == 2

    async def test_delete_and_finalize(self, user_alice):
        graph = _build_graph()
        cfg = _cfg("doc-3")
        from maru_lang.graph.doc.state import build_doc_input
        await graph.ainvoke(build_doc_input("계약서", [1], ["T"], user_id=user_alice.id), config=cfg)
        val = await _interrupt_value(graph, cfg)
        first_id = _blocks(val["canvas"])[0]["block_id"]
        await graph.ainvoke(Command(resume={"op": "delete", "block_id": first_id}), config=cfg)
        canvas = await Canvas.filter(user=user_alice).first()
        head = await CanvasVersion.get(id=canvas.head_version_id)
        assert len(head.payload["sections"][0]["blocks"]) == 1
        # finalize ends the loop
        result = await graph.ainvoke(Command(resume={"op": "finalize"}), config=cfg)
        assert result.get("finalized") is True
        assert (await Canvas.get(id=canvas.id)).status == CanvasStatus.FINALIZED

    async def test_reorder_op(self, user_alice):
        graph = _build_graph()
        cfg = _cfg("doc-4")
        from maru_lang.graph.doc.state import build_doc_input
        await graph.ainvoke(build_doc_input("계약서", [1], ["T"], user_id=user_alice.id), config=cfg)
        val = await _interrupt_value(graph, cfg)
        ids = [b["block_id"] for b in _blocks(val["canvas"])]
        await graph.ainvoke(
            Command(resume={"op": "reorder", "order": [ids[1], ids[0]]}), config=cfg)
        canvas = await Canvas.filter(user=user_alice).first()
        head = await CanvasVersion.get(id=canvas.head_version_id)
        texts = [b["text"] for b in head.payload["sections"][0]["blocks"]]
        assert texts == ["제1조 본문 B", "제1조 본문 A"]

    async def test_load_path_skips_grounding(self, user_alice):
        # First, create a canvas via the new path.
        graph = _build_graph()
        cfg = _cfg("doc-5a")
        from maru_lang.graph.doc.state import build_doc_input
        await graph.ainvoke(build_doc_input("계약서", [1], ["T"], user_id=user_alice.id), config=cfg)
        canvas = await Canvas.filter(user=user_alice).first()

        # New thread with canvas_id set → load path → straight to await_edit.
        graph2 = _build_graph()
        cfg2 = _cfg("doc-5b")
        await graph2.ainvoke(
            build_doc_input("", [1], ["T"], user_id=user_alice.id, canvas_id=canvas.id), config=cfg2)
        val = await _interrupt_value(graph2, cfg2)
        assert val["type"] == "awaiting_edit"
        assert val["canvas_id"] == canvas.id
        assert len(_blocks(val["canvas"])) == 2
        assert (await Canvas.get(id=canvas.id)).status == CanvasStatus.EDITING

    async def test_client_canvas_type_skips_classification(self, user_alice):
        # An explicit canvas_type bypasses the LLM classify call and pins the preset.
        graph = _build_graph()
        cfg = _cfg("doc-6")
        from maru_lang.graph.doc.state import build_doc_input
        await graph.ainvoke(
            build_doc_input("문서", [1], ["T"], user_id=user_alice.id, canvas_type="proposal"),
            config=cfg)
        canvas = await Canvas.filter(user=user_alice, canvas_type="proposal").first()
        assert canvas is not None
        assert canvas.schema_version == "proposal.v1"


class TestDocGraphSecurity:
    async def test_cross_user_canvas_id_is_not_loaded(self, user_alice, user_bob):
        # alice creates a canvas
        graph = _build_graph()
        from maru_lang.graph.doc.state import build_doc_input
        await graph.ainvoke(
            build_doc_input("계약서", [1], ["T"], user_id=user_alice.id), config=_cfg("sec-1a"))
        canvas = await Canvas.filter(user=user_alice).first()

        # bob tries to open alice's canvas by id on a fresh thread
        graph2 = _build_graph()
        cfg = _cfg("sec-1b")
        await graph2.ainvoke(
            build_doc_input("", [1], ["T"], user_id=user_bob.id, canvas_id=canvas.id), config=cfg)
        # read-only empty view (no leak), no edit loop, canvas untouched
        val = await _interrupt_value(graph2, cfg)
        assert val is None  # routed to END, no awaiting_edit interrupt
        # bob cannot mutate it either
        before = await CanvasVersion.filter(canvas=canvas).count()
        await graph2.ainvoke(
            Command(resume={"op": "delete", "block_id": "blk_001_001"}), config=cfg)
        assert await CanvasVersion.filter(canvas=canvas).count() == before

    async def test_finalized_canvas_cannot_be_reedited(self, user_alice):
        graph = _build_graph()
        cfg = _cfg("sec-2")
        from maru_lang.graph.doc.state import build_doc_input
        await graph.ainvoke(
            build_doc_input("계약서", [1], ["T"], user_id=user_alice.id), config=cfg)
        await graph.ainvoke(Command(resume={"op": "finalize"}), config=cfg)
        canvas = await Canvas.filter(user=user_alice).first()
        assert canvas.status == CanvasStatus.FINALIZED
        versions = await CanvasVersion.filter(canvas=canvas).count()

        # reopen by canvas_id on a fresh thread → read-only (END), stays FINALIZED
        graph2 = _build_graph()
        cfg2 = _cfg("sec-2b")
        await graph2.ainvoke(
            build_doc_input("", [1], ["T"], user_id=user_alice.id, canvas_id=canvas.id), config=cfg2)
        assert await _interrupt_value(graph2, cfg2) is None  # no edit loop
        reloaded = await Canvas.get(id=canvas.id)
        assert reloaded.status == CanvasStatus.FINALIZED          # not downgraded
        assert await CanvasVersion.filter(canvas=canvas).count() == versions  # no new version

    async def test_malformed_edit_op_does_not_crash_turn(self, user_alice):
        graph = _build_graph()
        cfg = _cfg("sec-3")
        from maru_lang.graph.doc.state import build_doc_input
        await graph.ainvoke(
            build_doc_input("계약서", [1], ["T"], user_id=user_alice.id), config=cfg)
        canvas = await Canvas.filter(user=user_alice).first()
        versions = await CanvasVersion.filter(canvas=canvas).count()

        # missing block_id → no crash, no new version, error surfaced, loop alive
        await graph.ainvoke(Command(resume={"op": "delete"}), config=cfg)
        assert await CanvasVersion.filter(canvas=canvas).count() == versions
        val = await _interrupt_value(graph, cfg)
        assert val["type"] == "awaiting_edit"
        assert "block_id" in val.get("error", "")
        # the loop still works: a valid op afterwards applies
        first_id = _blocks(val["canvas"])[0]["block_id"]
        await graph.ainvoke(Command(resume={"op": "delete", "block_id": first_id}), config=cfg)
        assert await CanvasVersion.filter(canvas=canvas).count() == versions + 1


class TestFinalizeSummary:
    def test_summarize_canvas_is_structured(self):
        from types import SimpleNamespace
        from maru_lang.graph.doc.nodes.finalize import _summarize_canvas
        canvas = SimpleNamespace(canvas_type="contract", title=None)
        payload = {
            "metadata": {"title": "업무위탁계약서",
                         "parties": [{"label": "갑", "name": "주식회사 케이씨"}, {"label": "을"}]},
            "sections": [{"blocks": [{}, {}]}, {"blocks": [{}]}],
            "missing_terms": [{"label": "계약금액"}],
        }
        s = _summarize_canvas(canvas, payload)
        assert "계약서" in s and "업무위탁계약서" in s   # preset label + title
        assert "주식회사 케이씨" in s and "을" in s       # parties
        assert "2개 섹션/3블록" in s                       # structure counts
        assert "미정 1건" in s                              # open items


class TestPresets:
    """Preset registry + keyword classification (pure)."""

    def test_get_preset_falls_back_to_generic(self):
        from maru_lang.graph.doc.presets import get_preset
        assert get_preset("contract").id == "contract"
        assert get_preset("nope").id == "generic"
        assert get_preset(None).id == "generic"

    def test_keyword_classification(self):
        from maru_lang.graph.doc.presets import match_by_keyword
        assert match_by_keyword("용역계약서 초안 작성해줘") == "contract"
        assert match_by_keyword("기안서 좀 써줘") == "proposal"
        assert match_by_keyword("그냥 메모") is None

    def test_preset_to_state_carries_scaffold_and_parties(self):
        from maru_lang.graph.doc.presets import get_preset
        ps = get_preset("contract").to_state()
        assert ps["schema_version"] == "contract.v1"
        assert "전문" in ps["scaffold"]
        assert [p["label"] for p in ps["parties"]] == ["갑", "을"]
        assert ps["anchor_family"] == ["계약"]


class TestReferenceRanking:
    """Anchor candidate ranking (pure)."""

    def test_relevance_prefers_matching_subtype(self):
        from maru_lang.graph.doc.nodes.bind import _relevance
        instr = "용역계약서 초안 작성해줘"
        assert _relevance(instr, "표준 용역계약서") > _relevance(instr, "표준 위탁계약서")

    def test_rank_orders_by_relevance(self):
        from types import SimpleNamespace
        from maru_lang.graph.doc.nodes.bind import _rank
        docs = [SimpleNamespace(id="b", name="표준 위탁계약서"),
                SimpleNamespace(id="a", name="표준 용역계약서")]
        ranked = _rank("용역계약서 작성", docs)
        assert ranked[0][0].id == "a"   # 용역 wins


class TestReferenceBinding:
    async def test_find_template_documents_filters_family_and_marker(self, user_alice):
        team = await _team_with_templates(user_alice, {
            "t1": "표준 용역계약서",     # family 계약 + marker 표준  → match
            "t2": "용역계약서 작성본",   # family 계약, no marker      → excluded
            "t3": "표준 취업규칙",       # marker 표준, no family 계약  → excluded
        })
        from maru_lang.services.document import find_template_documents
        found = await find_template_documents([team.id], ["계약"], ["표준", "양식"])
        assert [d.id for d in found] == ["t1"]

    async def test_single_template_auto_binds(self, user_alice):
        team = await _team_with_templates(user_alice, {"t1": "표준 용역계약서"})
        vdb = _mock_vdb({"t1": "표준 용역계약서"})
        graph = _build_graph(vdb)
        cfg = _cfg("doc-bind-1")
        from maru_lang.graph.doc.state import build_doc_input
        await graph.ainvoke(
            build_doc_input("용역계약서 초안 작성", [team.id], ["T"], user_id=user_alice.id),
            config=cfg)
        vdb.get_documents.assert_called_once_with(["t1"])
        # paused at edit (not a choice), and the anchor is recorded on the canvas
        val = await _interrupt_value(graph, cfg)
        assert val["type"] == "awaiting_edit"
        canvas = await Canvas.filter(user=user_alice).first()
        assert any(r.get("kind") == "anchor" and r["document_id"] == "t1"
                   for r in canvas.references)

    async def test_ambiguous_templates_prompt_choice_then_bind(self, user_alice):
        team = await _team_with_templates(user_alice, {
            "t1": "표준 용역계약서", "t2": "표준 위탁계약서"})
        vdb = _mock_vdb({"t1": "표준 용역계약서", "t2": "표준 위탁계약서"})
        graph = _build_graph(vdb)
        cfg = _cfg("doc-bind-2")
        from maru_lang.graph.doc.state import build_doc_input
        # vague request → neither standard clearly wins → choice interrupt
        await graph.ainvoke(
            build_doc_input("계약서 초안 작성해줘", [team.id], ["T"], user_id=user_alice.id),
            config=cfg)
        val = await _interrupt_value(graph, cfg)
        assert val["type"] == "awaiting_anchor_choice"
        assert {c["document_id"] for c in val["candidates"]} == {"t1", "t2"}
        # no canvas yet (paused before drafting)
        assert await Canvas.filter(user=user_alice).count() == 0
        # user picks the first → proceeds, binds it, drafts, pauses at edit
        await graph.ainvoke(Command(resume={"index": 0}), config=cfg)
        val2 = await _interrupt_value(graph, cfg)
        assert val2["type"] == "awaiting_edit"
        canvas = await Canvas.filter(user=user_alice).first()
        picked = val["candidates"][0]["document_id"]
        assert any(r.get("kind") == "anchor" and r["document_id"] == picked
                   for r in canvas.references)

    async def test_anchor_choice_skip_falls_back_to_rag(self, user_alice):
        team = await _team_with_templates(user_alice, {
            "t1": "표준 용역계약서", "t2": "표준 위탁계약서"})
        vdb = _mock_vdb({"t1": "표준 용역계약서", "t2": "표준 위탁계약서"})
        graph = _build_graph(vdb)
        cfg = _cfg("doc-bind-3")
        from maru_lang.graph.doc.state import build_doc_input
        await graph.ainvoke(
            build_doc_input("계약서 초안", [team.id], ["T"], user_id=user_alice.id), config=cfg)
        await graph.ainvoke(Command(resume={"skip": True}), config=cfg)
        val = await _interrupt_value(graph, cfg)
        assert val["type"] == "awaiting_edit"
        canvas = await Canvas.filter(user=user_alice).first()
        assert not any(r.get("kind") == "anchor" for r in canvas.references)
