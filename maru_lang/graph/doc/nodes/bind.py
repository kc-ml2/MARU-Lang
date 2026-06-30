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
import re

from langgraph.types import interrupt

from maru_lang.graph.doc.state import DocState
from maru_lang.services.document import find_template_documents

# Auto-bind only when the top candidate is relevant enough AND clearly ahead of
# the runner-up; otherwise ask. (Scores are char-bigram coverage in [0, 1].)
_MIN_SCORE = 0.34
_MIN_MARGIN = 0.15
_MAX_CANDIDATES = 5  # how many to surface on the choice interrupt


def _bigrams(s: str) -> set[str]:
    s = re.sub(r"\s+", "", s or "")
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
        {
            "chunk_id": c.id,
            "document_id": c.metadata.get("document_id", "unknown"),
            "document_name": c.metadata.get("document_name", ""),
            "score": c.metadata.get("score"),
            "content": c.page_content,
            "kind": "anchor",
        }
        for c in chunks
    ]


def _build_anchor_context(refs: list[dict]) -> str:
    names = ", ".join(sorted({r["document_name"] for r in refs if r.get("document_name")}))
    header = (f"[기준 문서{(' : ' + names) if names else ''}] "
              "아래는 표준 양식이다. 구조와 표현을 우선 참고해 작성하라.")
    body = "\n\n---\n\n".join(
        f"[{r['chunk_id']}] {r.get('document_name', '')}\n{r['content']}" for r in refs
    )
    return f"{header}\n\n{body}"


async def _load_anchor(vdb, document_id: str) -> dict:
    """Pull a document's chunks from the vector DB and build the anchor payload."""
    chunks = await asyncio.to_thread(vdb.get_documents, [document_id])
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

        if not family or not team_ids:
            return {"anchor_pending": False}

        candidates = await find_template_documents(team_ids, family, markers)
        if not candidates:
            return {"anchor_pending": False}

        ranked = _rank(instruction, candidates)
        clear_winner = len(ranked) == 1 or (
            ranked[0][1] >= _MIN_SCORE and (ranked[0][1] - ranked[1][1]) >= _MIN_MARGIN
        )
        if clear_winner:
            bound = await _load_anchor(vdb, ranked[0][0].id)
            return {**bound, "anchor_pending": False}

        # Ambiguous → let the user choose (don't guess the wrong standard).
        return {
            "anchor_pending": True,
            "anchor_candidates": [
                {"document_id": d.id, "name": d.name, "score": round(s, 3)}
                for d, s in ranked[:_MAX_CANDIDATES]
            ],
        }

    return bind_reference_node


def anchor_route(state: DocState) -> str:
    """After bind: pause for a choice when ambiguous, else proceed to ground."""
    return "await_anchor_choice" if state.get("anchor_pending") else "ground"


def await_anchor_choice_node(state: DocState) -> dict:
    """Pause for the user to pick a baseline document among the candidates."""
    choice = interrupt({
        "type": "awaiting_anchor_choice",
        "candidates": state.get("anchor_candidates", []),
    })
    return {"anchor_choice": choice if isinstance(choice, dict) else {"skip": True}}


def make_resolve_anchor_node(vdb):
    """Bind the user's chosen baseline document (or skip → pure RAG)."""

    async def resolve_anchor_node(state: DocState) -> dict:
        choice = state.get("anchor_choice") or {}
        candidates = state.get("anchor_candidates") or []
        if choice.get("skip"):
            return {"anchor_references": [], "anchor_context": None}

        document_id = choice.get("document_id")
        idx = choice.get("index")
        if document_id is None and isinstance(idx, int) and 0 <= idx < len(candidates):
            document_id = candidates[idx]["document_id"]
        if document_id is None:
            return {"anchor_references": [], "anchor_context": None}

        return await _load_anchor(vdb, document_id)

    return resolve_anchor_node
