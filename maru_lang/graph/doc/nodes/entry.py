"""Entry routing — new canvas (ground→draft) vs load an existing canvas from DB."""
from maru_lang.enums.chat import CanvasStatus
from maru_lang.graph.doc.state import DocState
from maru_lang.services.canvas import (
    load_head,
    serialize_canvas,
    set_status,
)


def entry_router(state: DocState) -> str:
    """Route to load_canvas when a canvas_id is supplied (reconnect/edit), else
    classify (new-canvas path: pick a preset → ground → draft)."""
    return "load_canvas" if state.get("canvas_id") else "classify"


def make_load_canvas_node():
    """Load an existing canvas's head version into state (ownership-scoped).

    A FINALIZED canvas is loaded read-only (not downgraded to EDITING); the graph
    routes it straight to END so a locked document can't be reopened for edits.
    """

    async def load_canvas_node(state: DocState) -> dict:
        canvas_id = state.get("canvas_id")
        # Ownership-scoped: only the canvas's owner can load it.
        loaded = await load_head(canvas_id, user_id=state.get("user_id")) if canvas_id else None
        if loaded is None:
            # Missing/unauthorized/invalid → empty read-only view (no edit loop).
            return {
                "payload": {},
                "finalized": True,
                "canvas_payload": {"canvas_id": canvas_id, "sections": []},
            }

        canvas, version = loaded
        locked = canvas.status == CanvasStatus.FINALIZED
        if not locked:
            await set_status(canvas, CanvasStatus.EDITING)
        payload = (version.payload if version else None) or {}
        return {
            "canvas_id": canvas.id,
            "canvas_type": canvas.canvas_type,
            "references": canvas.references or [],
            "payload": payload,
            "version_id": version.id if version else None,
            "finalized": locked,   # locked → routed to END (read-only)
            "canvas_payload": serialize_canvas(canvas, version),
        }

    return load_canvas_node


def post_load_route(state: DocState) -> str:
    """After load: a finalized (locked) or missing canvas is read-only → END;
    otherwise enter the edit loop."""
    return "end" if state.get("finalized") else "await_edit"
