"""Edit loop — interrupt for the next op, then append a new canvas version.

`await_edit` pauses with the current canvas; the client resumes with an edit
command dict: {op: edit|add|delete|reorder|finalize, ...}. `apply_edit` reloads
the head version (single source of truth), applies one tree op, and appends a new
immutable version, then loops back to await_edit.
"""
import copy

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.types import interrupt

from maru_lang.constants import DOC_BLOCK_EDIT_PROMPT
from maru_lang.enums.chat import CanvasStatus
from maru_lang.graph.doc.state import DocState
from maru_lang.services.canvas import (
    add_block,
    delete_block,
    empty_payload,
    find_block,
    iter_blocks,
    load_head,
    reorder_blocks,
    serialize_canvas,
    set_block_text,
    set_status,
    write_version,
)


def await_edit_node(state: DocState) -> dict:
    """Pause for the next edit command, surfacing the current canvas.

    If the previous op was rejected (malformed/locked/not-found) its reason is
    surfaced as `error` so the client can correct and retry. Resuming clears it.
    """
    value = {
        "type": "awaiting_edit",
        "canvas_id": state.get("canvas_id"),
        "canvas": state.get("canvas_payload") or {},
    }
    if state.get("edit_error"):
        value["error"] = state["edit_error"]
    op = interrupt(value)
    return {"edit_op": op if isinstance(op, dict) else {"op": "finalize"}, "edit_error": None}


def apply_edit_route(state: DocState) -> str:
    """finalize ends the loop; anything else applies an edit."""
    op = (state.get("edit_op") or {}).get("op")
    return "finalize" if op == "finalize" else "apply_edit"


def _doc_context(payload: dict) -> str:
    """All blocks as `[block_id] text` lines, for edit prompt context."""
    return "\n".join(
        f"[{b.get('block_id')}] {b.get('text', '')}" for _s, b in iter_blocks(payload)
    )


def make_apply_edit_node(llm: BaseChatModel):
    """Apply one edit op (edit/add/delete/reorder) by appending a new version."""

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
        canvas_type = canvas.canvas_type or "문서"

        # Validate + apply. A malformed/no-op command never crashes the turn:
        # it leaves the canvas unchanged and reports `edit_error` to the client.
        changed = False
        error = None
        try:
            if op == "edit":
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

            elif op == "add":
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
                new_id = add_block(
                    payload,
                    block={"block_type": edit_op.get("block_type", "paragraph"),
                           "text": content or ""},
                    after_block_id=str(after) if after is not None else None,
                    section_id=edit_op.get("section_id"),
                )
                changed = new_id is not None
                if not changed:
                    error = "블록을 추가할 섹션이 없습니다."

            elif op == "delete":
                block_id = edit_op.get("block_id")
                if block_id is None:
                    error = "delete에는 block_id가 필요합니다."
                else:
                    changed = delete_block(payload, str(block_id))
                    if not changed:
                        error = f"블록을 찾을 수 없습니다: {block_id}"

            elif op == "reorder":
                order = edit_op.get("order") or []
                changed = reorder_blocks(
                    payload, [str(i) for i in order], section_id=edit_op.get("section_id"))
                if not changed:
                    error = "재정렬할 블록을 찾을 수 없습니다."
            else:
                error = f"알 수 없는 편집 명령: {op}"
        except Exception as e:  # defensive: malformed payloads never break the turn
            error = f"편집 처리 오류: {type(e).__name__}"

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
            "edit_error": None,
        }

    return apply_edit_node
