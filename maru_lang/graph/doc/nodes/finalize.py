"""Finalize node — lock the canvas (status=FINALIZED), record the turn, end."""
from langchain_core.messages import AIMessage

from maru_lang.core.relation_db.models.auth import User
from maru_lang.core.relation_db.models.chat import Session
from maru_lang.graph.doc.presets import get_preset
from maru_lang.graph.doc.state import DocState
from maru_lang.services.canvas import finalize_canvas, get_canvas
from maru_lang.services.chat import create_conversation


def _summarize_canvas(canvas, payload: dict) -> str:
    """A deterministic one-line summary of the finalized document, built from its
    structure (no LLM): doc type, title, parties, section/block counts, open items.

    The Canvas is the durable artifact and already holds all content; this string
    is only for the session/conversation history line, so a templated summary is
    cheaper and more reliable than an LLM pass.
    """
    meta = payload.get("metadata") or {}
    sections = payload.get("sections") or []
    label = get_preset(canvas.canvas_type).label if canvas.canvas_type else "문서"
    title = meta.get("title") or canvas.title

    n_sections = len(sections)
    n_blocks = sum(len(s.get("blocks") or []) for s in sections)
    n_missing = len(payload.get("missing_terms") or [])
    parties = [
        (p.get("name") or p.get("label") or "").strip()
        for p in (meta.get("parties") or [])
    ]
    party_s = "·".join(p for p in parties if p)

    head = f"{label} '{title}'" if title else label
    bits = []
    if party_s:
        bits.append(party_s)
    bits.append(f"{n_sections}개 섹션/{n_blocks}블록")
    if n_missing:
        bits.append(f"미정 {n_missing}건")
    return f"{head} 확정 · " + " · ".join(bits)


def make_finalize_node():
    async def finalize_node(state: DocState) -> dict:
        canvas_id = state.get("canvas_id")
        user_id = state.get("user_id")
        payload = state.get("payload") or {}

        canvas = None
        if canvas_id:
            # Ownership-scoped: only the owner can finalize their canvas.
            canvas = await get_canvas(canvas_id, user_id=user_id)
            if canvas is not None:
                await finalize_canvas(canvas)

        if canvas is not None:
            summary = _summarize_canvas(canvas, payload)
        else:
            n = sum(len(s.get("blocks") or []) for s in payload.get("sections") or [])
            summary = f"문서를 확정했습니다 (블록 {n}개)."

        # Persist the authoring turn into the chat session history (gated on
        # user_id+session_id, mirroring the RAG graph's terminal write-back).
        # The canvas itself is the durable artifact; this row links the session
        # to it so the conversation list shows the completed document.
        if canvas is not None and user_id and state.get("session_id"):
            user = await User.get_or_none(id=user_id)
            session = await Session.get_or_none(id=state["session_id"])
            if user is not None:
                await create_conversation(
                    user,
                    question=state.get("instruction") or "(문서 작성)",
                    answer=f"문서를 확정했습니다 — {summary}",
                    references=canvas.references or [],
                    session=session,
                    summary=summary,
                )

        return {"finalized": True, "messages": [AIMessage(content=f"문서를 확정했습니다 — {summary}")]}

    return finalize_node
