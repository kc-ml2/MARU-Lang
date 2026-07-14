"""Constants cohesive to the document-authoring (doc) graph.

Vocabulary shared across the doc graph's own modules: the edit-op names and
interrupt `type` tags form the resume protocol with the client, so their string
values are a stable contract. The doc prompt templates (DOC_*_PROMPT) live in
maru_lang.constants alongside the other LLM prompts.
"""
from typing import TypedDict

# ---- edit ops (client resume payload {"op": ...}; also the apply_edit dispatch) ----
OP_EDIT = "edit"
OP_ADD = "add"
OP_DELETE = "delete"
OP_REORDER = "reorder"
OP_SET_PARTIES = "set_parties"  # fill structured metadata.parties (갑/을 정보)
OP_SET_TERMS = "set_terms"      # fill undetermined values: {{label}} 토큰 치환 + missing_terms 제거
OP_BATCH = "batch"              # apply several ops as one version {"op":"batch","ops":[...]}
OP_FINALIZE = "finalize"

# ---- interrupt `type` tags surfaced to the client (resume-protocol contract) ----
INTERRUPT_ANCHOR_CHOICE = "awaiting_anchor_choice"
INTERRUPT_EDIT = "awaiting_edit"


# ---- anchor-choice interrupt contract (awaiting_anchor_choice) ----
# The shapes below are the authoritative type definition for the frontend: the
# payload is built deterministically in bind.py (no LLM), so these are fixed. The
# interrupt reaches the client wrapped as {"type":"interrupt","content": <an
# AnchorChoiceInterrupt>}; the client replies {"type":"resume","content": <an
# AnchorChoice>}.

class AnchorCandidate(TypedDict):
    """One baseline/standard document the user may pick as a grounding anchor."""
    document_id: str    # Document.id — echo back inside AnchorChoice.document_ids
    name: str           # display name; may be Hangul NFD — NFC-normalize before showing
    score: float        # relevance to the request, 0..1, rounded to 3 decimals


class AnchorChoiceInterrupt(TypedDict):
    """Interrupt value surfaced when the standard doc is ambiguous (content of the
    "interrupt" ws message)."""
    type: str                          # always INTERRUPT_ANCHOR_CHOICE
    candidates: list[AnchorCandidate]  # up to _MAX_CANDIDATES (5)


class AnchorChoice(TypedDict, total=False):
    """Client resume payload for an anchor choice (content of the "resume" ws
    message). Resolution in resolve_anchor_node: skip takes precedence; otherwise
    every id in document_ids is bound as an anchor (empty/absent → no anchor).
    anchor_only is an orthogonal modifier."""
    document_ids: list[str]   # pick one or more candidates to bind as anchors
    skip: bool                # true → bind no anchor, ground via pure RAG (precedence)
    anchor_only: bool         # modifier: ground on the chosen anchors alone (skip fuzzy RAG)

# ---- reference kinds ----
# Marks a chunk bound as a standard/baseline anchor vs a fuzzy RAG hit.
REF_KIND_ANCHOR = "anchor"

# ---- shared fallbacks ----
DEFAULT_DOC_LABEL = "문서"      # human label when no preset/canvas_type resolves
UNKNOWN_DOC_ID = "unknown"      # document_id when a chunk lacks one
FREE_STRUCTURE = "(자유 구조)"  # scaffold text for a preset with no fixed sections
