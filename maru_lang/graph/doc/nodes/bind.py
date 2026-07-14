"""Bind a baseline/standard document as a deterministic grounding anchor.

For families like contracts a team usually keeps a canonical standard document
("표준 용역계약서"). Relying on fuzzy RAG to surface it is unreliable, so this node
deterministically finds the team's template candidates, ranks them against the
request, and binds the best match as a labeled anchor in the draft context —
separate from (and prepended to) the fuzzy RAG hits.

When several standards plausibly fit (e.g. 표준 용역계약서 vs 표준 위탁계약서 for a
vague "계약서" request), it interrupts (`awaiting_anchor_choice`) and lets the user
pick rather than guessing. A clear winner (or a lone candidate) binds automatically.
"""
import asyncio
import logging
import re
import unicodedata

from langgraph.types import interrupt

from maru_lang.graph.doc.constants import (
    AnchorCandidate,
    AnchorChoiceInterrupt,
    INTERRUPT_ANCHOR_CHOICE,
    REF_KIND_ANCHOR,
)
from maru_lang.graph.doc.refs import base_ref, render_ref_context
from maru_lang.graph.doc.state import DocState
from maru_lang.services.document import find_template_documents

logger = logging.getLogger(__name__)

# Auto-bind only when the top candidate is relevant enough AND clearly ahead of
# the runner-up; otherwise ask. (Scores are char-bigram coverage in [0, 1].)
_MIN_SCORE = 0.34
_MIN_MARGIN = 0.15
_MAX_CANDIDATES = 5  # how many to surface on the choice interrupt


def _bigrams(s: str) -> set[str]:
    # NFC-normalize first: the instruction is NFC but a candidate name may be NFD
    # (macOS uploads), and jamo-level bigrams would never overlap → relevance 0.
    s = unicodedata.normalize("NFC", s or "")
    s = re.sub(r"\s+", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _relevance(instruction: str, name: str) -> float:
    """Fraction of the candidate name's bigrams covered by the request (0..1)."""
    a, b = _bigrams(instruction), _bigrams(name)
    return (len(a & b) / len(b)) if b else 0.0


def _rank(instruction: str, docs) -> list[tuple]:
    """Candidates as (doc, score) sorted by relevance to the request, desc."""
    scored = [(d, _relevance(instruction, d.name)) for d in docs]
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored


def _to_anchor_refs(chunks) -> list[dict]:
    return [
        {**base_ref(c, score_default=None), "kind": REF_KIND_ANCHOR}
        for c in chunks
    ]


def _build_anchor_context(refs: list[dict]) -> str:
    names = sorted({r["document_name"] for r in refs if r.get("document_name")})
    label = ", ".join(names)
    # One anchor → "표준 양식"; several → "표준 양식들" + 종합 지시 (multi-doc select).
    if len(names) > 1:
        header = (f"[기준 문서 : {label}] 아래는 기준으로 삼을 표준 양식들이다. "
                  "여러 문서를 요청에 맞게 종합해 구조와 표현을 우선 참고해 작성하라.")
    else:
        header = (f"[기준 문서{(' : ' + label) if label else ''}] "
                  "아래는 표준 양식이다. 구조와 표현을 우선 참고해 작성하라.")
    return f"{header}\n\n{render_ref_context(refs)}"


async def _load_anchors(vdb, document_ids: list[str]) -> dict:
    """Pull chunks for one or more documents from the vector DB and build the anchor
    payload. Multiple docs' chunks are merged into one anchor context/references set."""
    ids = [i for i in (document_ids or []) if i]
    if not ids:
        return {"anchor_references": [], "anchor_context": None}
    chunks = await asyncio.to_thread(vdb.get_documents, ids)
    if not chunks:
        return {"anchor_references": [], "anchor_context": None}
    refs = _to_anchor_refs(chunks)
    return {"anchor_references": refs, "anchor_context": _build_anchor_context(refs)}


def make_bind_reference_node(vdb):
    """Find + rank template candidates; auto-bind a clear winner, else ask."""

    async def bind_reference_node(state: DocState) -> dict:
        preset = state.get("preset") or {}
        family = preset.get("anchor_family") or []
        markers = preset.get("anchor_markers") or []
        team_ids = state.get("team_ids") or []
        instruction = state.get("instruction") or ""

        logger.debug(
            "[bind] family=%s markers=%s team_ids=%s instruction=%r",
            family, markers, team_ids, instruction[:60],
        )

        if not family or not team_ids:
            logger.debug(
                "[bind] early-exit: no anchor bound (family=%s, team_ids=%s)",
                family, team_ids,
            )
            return {"anchor_pending": False}

        candidates = await find_template_documents(team_ids, family, markers)
        logger.debug(
            "[bind] find_template_documents → %d candidate(s): %s",
            len(candidates), [c.name for c in candidates],
        )
        if not candidates:
            logger.debug(
                "[bind] early-exit: 0 template candidates matched "
                "(name must contain ALL of %s AND one of %s, status=ACTIVE, teams=%s)",
                family, markers, team_ids,
            )
            return {"anchor_pending": False}

        ranked = _rank(instruction, candidates)
        logger.debug(
            "[bind] ranked: %s (min_score=%s, min_margin=%s)",
            [(d.name, round(s, 3)) for d, s in ranked], _MIN_SCORE, _MIN_MARGIN,
        )
        clear_winner = len(ranked) == 1 or (
            ranked[0][1] >= _MIN_SCORE and (ranked[0][1] - ranked[1][1]) >= _MIN_MARGIN
        )
        if clear_winner:
            logger.debug("[bind] auto-bind clear winner: %s", ranked[0][0].name)
            bound = await _load_anchors(vdb, [ranked[0][0].id])
            return {**bound, "anchor_pending": False}

        # Ambiguous → let the user choose (don't guess the wrong standard).
        logger.debug("[bind] ambiguous → interrupt for user choice (%d candidates)", len(ranked))
        candidates_out: list[AnchorCandidate] = [
            {"document_id": d.id, "name": d.name, "score": round(s, 3)}
            for d, s in ranked[:_MAX_CANDIDATES]
        ]
        return {
            "anchor_pending": True,
            "anchor_candidates": candidates_out,
        }

    return bind_reference_node


def anchor_route(state: DocState) -> str:
    """After bind: pause for a choice when ambiguous, else proceed to ground."""
    return "await_anchor_choice" if state.get("anchor_pending") else "ground"


def await_anchor_choice_node(state: DocState) -> dict:
    """Pause for the user to pick one or more baseline documents among the candidates."""
    payload: AnchorChoiceInterrupt = {
        "type": INTERRUPT_ANCHOR_CHOICE,
        "candidates": state.get("anchor_candidates", []),
    }
    choice = interrupt(payload)
    return {"anchor_choice": choice if isinstance(choice, dict) else {"skip": True}}


def make_resolve_anchor_node(vdb):
    """Bind the user's chosen baseline document (or skip → pure RAG)."""

    async def resolve_anchor_node(state: DocState) -> dict:
        choice = state.get("anchor_choice") or {}
        # The pick may force anchor-only for this doc (ground on the chosen
        # standards alone). If unset, the turn's default (/anchor) stands.
        override = {"anchor_only": True} if choice.get("anchor_only") else {}
        if choice.get("skip"):
            return {"anchor_references": [], "anchor_context": None, **override}

        # One or more chosen standards → bind them all as merged anchors.
        document_ids = [i for i in (choice.get("document_ids") or []) if i]
        if not document_ids:
            return {"anchor_references": [], "anchor_context": None, **override}

        return {**await _load_anchors(vdb, document_ids), **override}

    return resolve_anchor_node
