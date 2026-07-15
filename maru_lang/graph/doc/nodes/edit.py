"""Edit loop — interrupt for the next op, then append a new canvas version.

`await_edit` pauses with the current canvas; the client resumes with an edit
command dict: {op: edit|add|delete|reorder|set_parties|set_terms|regenerate|finalize,
...}, or a batch {op: "batch", ops: [...]} to apply several as one version. `apply_edit`
reloads the head version (single source of truth), applies the op(s), and appends a
new immutable version, then loops back to await_edit. `regenerate` is the exception
that doesn't mutate the loaded tree: it redrafts the whole document from the original
grounding steered by the user's feedback (see nodes/draft.generate_canvas_tree).

For contracts the drafted parties (갑/을) are seeded empty; await_edit surfaces the
still-blank ones as `missing_parties` so the client can prompt for them, and the
`set_parties` op fills the structured metadata.parties (which block ops don't touch).
"""
import copy

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.types import interrupt

from maru_lang.constants import DOC_BLOCK_EDIT_PROMPT
from maru_lang.enums.chat import CanvasStatus
from maru_lang.graph.doc.constants import (
    DEFAULT_DOC_LABEL,
    INTERRUPT_EDIT,
    OP_ADD,
    OP_BATCH,
    OP_DELETE,
    OP_EDIT,
    OP_FINALIZE,
    OP_REDO,
    OP_REGENERATE,
    OP_REORDER,
    OP_SET_PARTIES,
    OP_SET_TERMS,
    OP_UNDO,
)
from maru_lang.graph.doc.nodes.draft import generate_canvas_tree
from maru_lang.graph.doc.refs import render_ref_context
from maru_lang.graph.doc.state import DocState
from maru_lang.services.canvas import (
    Party,
    add_block,
    delete_block,
    empty_payload,
    fill_terms,
    find_block,
    iter_blocks,
    load_head,
    next_version,
    previous_version,
    reorder_blocks,
    serialize_canvas,
    set_block_text,
    set_head,
    set_parties,
    set_status,
    write_version,
)


def _incomplete_parties(canvas_payload: dict | None) -> list[Party]:
    """Parties still missing a name — surfaced so the client can prompt for them.

    Non-contract docs seed no parties, so this is naturally empty for them.
    """
    meta = (canvas_payload or {}).get("metadata") or {}
    return [p for p in (meta.get("parties") or []) if not (p.get("name") or "").strip()]


async def _history_availability(state: DocState) -> tuple[bool, bool]:
    """(can_undo, can_redo) at the canvas's current head: is there a previous
    version to step back to, and a child to step forward to. Both False when the
    canvas isn't persisted yet (no-DB draft) or isn't owned/found."""
    canvas_id = state.get("canvas_id")
    if not canvas_id:
        return False, False
    loaded = await load_head(canvas_id, user_id=state.get("user_id"))
    if loaded is None:
        return False, False
    canvas, head = loaded
    can_undo = await previous_version(canvas, head) is not None
    can_redo = await next_version(canvas, head) is not None
    return can_undo, can_redo


async def await_edit_node(state: DocState) -> dict:
    """Pause for the next edit command, surfacing the current canvas.

    If the previous op was rejected (malformed/locked/not-found) its reason is
    surfaced as `error` so the client can correct and retry. Resuming clears it.
    """
    # The interrupt is a lean control signal ("paused, awaiting the next op for
    # canvas X"), NOT a carrier of the canvas body: await_edit is always reached
    # right after a node that already emitted the canvas (draft/load_canvas/
    # apply_edit) as a "canvas" event with this same canvas_id. So we send only
    # the id to correlate, plus prompts (missing_parties/error) and the history
    # flags. The client renders the canvas from the "canvas" event; this avoids
    # shipping the full tree twice.
    can_undo, can_redo = await _history_availability(state)
    value = {
        "type": INTERRUPT_EDIT,
        "canvas_id": state.get("canvas_id"),
        # Enable/disable the client's 되돌리기/다시실행 controls without a probe call.
        "can_undo": can_undo,
        "can_redo": can_redo,
    }
    missing = _incomplete_parties(state.get("canvas_payload"))
    if missing:
        # Prompt the client to collect these (resume with a set_parties op).
        value["missing_parties"] = missing
    if state.get("edit_error"):
        value["error"] = state["edit_error"]
    op = interrupt(value)
    return {"edit_op": op if isinstance(op, dict) else {"op": OP_FINALIZE}, "edit_error": None}


def apply_edit_route(state: DocState) -> str:
    """finalize ends the loop; anything else applies an edit."""
    op = (state.get("edit_op") or {}).get("op")
    return "finalize" if op == OP_FINALIZE else "apply_edit"


def _doc_context(payload: dict) -> str:
    """All blocks as `[block_id] text` lines, for edit prompt context."""
    return "\n".join(
        f"[{b.get('block_id')}] {b.get('text', '')}" for _s, b in iter_blocks(payload)
    )


async def _apply_one_op(
    llm: BaseChatModel, payload: dict, canvas_type: str, edit_op: dict,
) -> tuple[bool, str | None]:
    """Apply a single edit op to `payload` in place. Returns (changed, error).

    Never raises: a malformed op leaves the payload untouched and reports why, so
    one bad op inside a batch can't abort the rest of the turn.
    """
    op = edit_op.get("op")
    changed = False
    error = None
    try:
        if op == OP_EDIT:
            block_id = edit_op.get("block_id")
            if block_id is None:
                error = "edit에는 block_id가 필요합니다."
            else:
                _sec, block = find_block(payload, str(block_id))
                if block is None:
                    error = f"블록을 찾을 수 없습니다: {block_id}"
                else:
                    prompt = DOC_BLOCK_EDIT_PROMPT.format(
                        doc_type=canvas_type,
                        doc_context=_doc_context(payload),
                        block_body=block.get("text", ""),
                        feedback=edit_op.get("feedback", ""),
                    )
                    response = await llm.ainvoke([HumanMessage(content=prompt)])
                    # Clear source_refs: the block was rewritten by the LLM and its
                    # old refs may no longer ground the new text. We can't re-validate
                    # here, so drop them rather than show stale/false provenance.
                    changed = set_block_text(
                        payload, str(block_id), (response.content or "").strip(), source_refs=[])

        elif op == OP_ADD:
            content = edit_op.get("content")
            if content is None and edit_op.get("feedback"):
                prompt = DOC_BLOCK_EDIT_PROMPT.format(
                    doc_type=canvas_type,
                    doc_context=_doc_context(payload),
                    block_body="(새 블록)",
                    feedback=edit_op["feedback"],
                )
                response = await llm.ainvoke([HumanMessage(content=prompt)])
                content = (response.content or "").strip()
            after = edit_op.get("after_block_id")
            # Omit block_type when unset so add_block applies its own default.
            new_block = {"text": content or ""}
            if edit_op.get("block_type"):
                new_block["block_type"] = edit_op["block_type"]
            new_id = add_block(
                payload,
                block=new_block,
                after_block_id=str(after) if after is not None else None,
                section_id=edit_op.get("section_id"),
            )
            changed = new_id is not None
            if not changed:
                error = "블록을 추가할 섹션이 없습니다."

        elif op == OP_DELETE:
            block_id = edit_op.get("block_id")
            if block_id is None:
                error = "delete에는 block_id가 필요합니다."
            else:
                changed = delete_block(payload, str(block_id))
                if not changed:
                    error = f"블록을 찾을 수 없습니다: {block_id}"

        elif op == OP_REORDER:
            order = edit_op.get("order") or []
            changed = reorder_blocks(
                payload, [str(i) for i in order], section_id=edit_op.get("section_id"))
            if not changed:
                error = "재정렬할 블록을 찾을 수 없습니다."

        elif op == OP_SET_PARTIES:
            # Fill structured metadata.parties (갑/을) — block ops can't reach it.
            changed = set_parties(payload, edit_op.get("parties") or [])
            if not changed:
                error = "반영할 당사자 정보가 없습니다."

        elif op == OP_SET_TERMS:
            # Fill undetermined values: replace {{label}} tokens + drop from missing_terms.
            changed = fill_terms(payload, edit_op.get("terms") or [])
            if not changed:
                error = "반영할 미정 항목 값이 없습니다."
        else:
            error = f"알 수 없는 편집 명령: {op}"
    except Exception as e:  # defensive: malformed payloads never break the turn
        return False, f"편집 처리 오류: {type(e).__name__}"
    return changed, error


async def _apply_batch(
    llm: BaseChatModel, payload: dict, canvas_type: str, sub_ops: list,
) -> tuple[bool, str | None]:
    """Apply each op in `sub_ops` to `payload` in order (later ops see earlier
    changes). Returns (any_changed, combined_error). Individual failures are
    collected — a bad op is skipped, not fatal — so the good ones still land."""
    changed = False
    errors = []
    for i, sub in enumerate(sub_ops):
        sub_op = sub.get("op") if isinstance(sub, dict) else None
        if sub_op in (OP_BATCH, OP_FINALIZE, OP_REGENERATE, OP_UNDO, OP_REDO, None):
            errors.append(f"[{i}] 배치에 넣을 수 없는 항목: {sub_op}")
            continue
        sub_changed, sub_err = await _apply_one_op(llm, payload, canvas_type, sub)
        changed = changed or sub_changed
        if sub_err:
            errors.append(f"[{i}] {sub_err}")
    return changed, "; ".join(errors) or None


def _grounding_state(state: DocState, canvas) -> DocState:
    """State for a regenerate, backfilling grounding from the persisted canvas.

    In the same session that drafted the doc, the live state still holds the
    instruction/context/references, so this is a no-op. But when a fresh thread
    reloaded an existing canvas (load path), those fields are absent — rebuild the
    id-tagged context from the canvas's stored reference chunks so the redraft is
    still grounded on the original sources rather than starting blank.
    """
    gen = dict(state)
    if not gen.get("instruction"):
        gen["instruction"] = canvas.instruction or ""
    if not gen.get("canvas_type"):
        gen["canvas_type"] = canvas.canvas_type
    if not gen.get("context") and canvas.references:
        gen["references"] = canvas.references
        gen["context"] = render_ref_context(canvas.references)
    return gen


async def _regenerate(
    llm: BaseChatModel, state: DocState, canvas, current_payload: dict,
) -> tuple[bool, str | None, dict]:
    """Full redraft: regenerate the whole tree from the original grounding steered
    by the user's feedback. Returns (changed, error, payload). Keeps the user's
    already-filled 갑/을 names; filled inline term values reset (they're redrawn)."""
    feedback = (state.get("edit_op") or {}).get("feedback")
    feedback = feedback.strip() if isinstance(feedback, str) else ""
    if not feedback:
        return False, "재작성하려면 마음에 안 든 점을 feedback으로 보내주세요.", current_payload
    prior_parties = (current_payload.get("metadata") or {}).get("parties") or []
    new_payload, _meta = await generate_canvas_tree(
        llm, _grounding_state(state, canvas), feedback=feedback, prior_parties=prior_parties,
    )
    return True, None, new_payload


async def _navigate(canvas, version, op: str) -> dict:
    """Undo/redo: move the head pointer along the version lineage without writing a
    new snapshot. undo → the base (previous) version; redo → the latest child. A
    no-op at either end (nothing older / nothing newer) is reported, not fatal."""
    target = (
        await previous_version(canvas, version) if op == OP_UNDO
        else await next_version(canvas, version)
    )
    if target is None:
        msg = "되돌릴 이전 버전이 없습니다." if op == OP_UNDO else "다시 실행할 다음 버전이 없습니다."
        return {"canvas_payload": serialize_canvas(canvas, version), "edit_error": msg}
    await set_head(canvas, target)
    return {
        "payload": target.payload,
        "version_id": target.id,
        "canvas_payload": serialize_canvas(canvas, target),
        "edit_error": None,
    }


def make_apply_edit_node(llm: BaseChatModel):
    """Apply an edit op (edit/add/delete/reorder/set_parties/set_terms/regenerate, or
    a batch of them) by appending one new version — or undo/redo, which just re-point
    the head."""

    async def apply_edit_node(state: DocState) -> dict:
        edit_op = state.get("edit_op") or {}
        op = edit_op.get("op")
        canvas_id = state.get("canvas_id")
        # Ownership-scoped: only the owner's canvas is loadable/mutable.
        loaded = await load_head(canvas_id, user_id=state.get("user_id")) if canvas_id else None

        # Without a persisted/owned canvas we can't version; surface the reason.
        if loaded is None:
            return {
                "canvas_payload": state.get("canvas_payload") or {"sections": []},
                "edit_error": "편집할 문서를 찾을 수 없습니다.",
            }

        canvas, version = loaded

        # Locked: a finalized canvas is read-only — never write a new version.
        if canvas.status == CanvasStatus.FINALIZED:
            return {
                "canvas_payload": serialize_canvas(canvas, version),
                "edit_error": "확정된 문서는 편집할 수 없습니다.",
            }

        # Undo/redo just move the head pointer over existing snapshots — no new
        # version, no LLM, no payload mutation. Handle before the edit machinery.
        if op in (OP_UNDO, OP_REDO):
            return await _navigate(canvas, version, op)

        payload = copy.deepcopy((version.payload if version else None)
                                or state.get("payload") or empty_payload())
        canvas_type = canvas.canvas_type or DEFAULT_DOC_LABEL

        # Apply one op, or a batch of them, to the working payload. A malformed/no-op
        # command never crashes the turn: it leaves the canvas unchanged (batch:
        # partially applies) and reports `edit_error` to the client.
        if op == OP_REGENERATE:
            # Whole-doc redraft — replaces the tree rather than mutating it.
            changed, error, payload = await _regenerate(llm, state, canvas, payload)
        elif op == OP_BATCH:
            changed, error = await _apply_batch(
                llm, payload, canvas_type, edit_op.get("ops") or [])
        else:
            changed, error = await _apply_one_op(llm, payload, canvas_type, edit_op)

        if not changed:
            # No-op — keep the edit loop alive and tell the client why.
            return {"canvas_payload": serialize_canvas(canvas, version), "edit_error": error}

        if canvas.status != CanvasStatus.EDITING:
            await set_status(canvas, CanvasStatus.EDITING)
        new_version = await write_version(
            canvas, payload, base_version_id=version.id if version else None, op=edit_op,
        )
        return {
            "payload": payload,
            "version_id": new_version.id,
            "canvas_payload": serialize_canvas(canvas, new_version),
            # None on a clean apply; a batch with partial failures surfaces them.
            "edit_error": error,
        }

    return apply_edit_node
