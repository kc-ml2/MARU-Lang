"""Edit loop — interrupt for the next op, then append a new canvas version.

`await_edit` pauses with the current canvas; the client resumes with an edit
command dict: {op: edit|add|delete|reorder|set_parties|set_terms|finalize, ...}, or
a batch {op: "batch", ops: [...]} to apply several as one version. `apply_edit` reloads the
head version (single source of truth), applies the op(s), and appends a new
immutable version, then loops back to await_edit.

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
    OP_REORDER,
    OP_SET_PARTIES,
    OP_SET_TERMS,
)
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
    reorder_blocks,
    serialize_canvas,
    set_block_text,
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


def await_edit_node(state: DocState) -> dict:
    """Pause for the next edit command, surfacing the current canvas.

    If the previous op was rejected (malformed/locked/not-found) its reason is
    surfaced as `error` so the client can correct and retry. Resuming clears it.
    """
    value = {
        "type": INTERRUPT_EDIT,
        "canvas_id": state.get("canvas_id"),
        "canvas": state.get("canvas_payload") or {},
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
                    changed = set_block_text(payload, str(block_id), (response.content or "").strip())

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
        if sub_op in (OP_BATCH, OP_FINALIZE, None):
            errors.append(f"[{i}] 배치에 넣을 수 없는 항목: {sub_op}")
            continue
        sub_changed, sub_err = await _apply_one_op(llm, payload, canvas_type, sub)
        changed = changed or sub_changed
        if sub_err:
            errors.append(f"[{i}] {sub_err}")
    return changed, "; ".join(errors) or None


def make_apply_edit_node(llm: BaseChatModel):
    """Apply an edit op (edit/add/delete/reorder/set_parties, or a batch of them)
    by appending one new version."""

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

        payload = copy.deepcopy((version.payload if version else None)
                                or state.get("payload") or empty_payload())
        canvas_type = canvas.canvas_type or DEFAULT_DOC_LABEL

        # Apply one op, or a batch of them, to the working payload. A malformed/no-op
        # command never crashes the turn: it leaves the canvas unchanged (batch:
        # partially applies) and reports `edit_error` to the client.
        if op == OP_BATCH:
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
