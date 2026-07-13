"""Constants cohesive to the document-authoring (doc) graph.

Vocabulary shared across the doc graph's own modules: the edit-op names and
interrupt `type` tags form the resume protocol with the client, so their string
values are a stable contract. The doc prompt templates (DOC_*_PROMPT) live in
maru_lang.constants alongside the other LLM prompts.
"""

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

# ---- reference kinds ----
# Marks a chunk bound as a standard/baseline anchor vs a fuzzy RAG hit.
REF_KIND_ANCHOR = "anchor"

# ---- shared fallbacks ----
DEFAULT_DOC_LABEL = "문서"      # human label when no preset/canvas_type resolves
UNKNOWN_DOC_ID = "unknown"      # document_id when a chunk lacks one
FREE_STRUCTURE = "(자유 구조)"  # scaffold text for a preset with no fixed sections
