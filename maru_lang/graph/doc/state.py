"""State for the document-authoring (doc) graph.

The doc graph drafts a structured document (a *canvas* tree: sections → blocks)
from internal team docs, returns it whole, then loops over interrupt-driven edits
until the user finalizes. The DB (Canvas/CanvasVersion) is the durable source of
truth; this state is the in-flight working copy for one connected thread.
"""
from typing import Annotated, Optional, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph.message import add_messages


class DocState(TypedDict, total=False):
    # ---- identity / scope ----
    messages: Annotated[list[BaseMessage], add_messages]
    team_ids: list[int]
    team_names: list[str]
    session_id: Optional[str]
    user_id: Optional[int]
    llm_name: Optional[str]

    # ---- request ----
    instruction: Optional[str]      # this turn's authoring request
    canvas_type: Optional[str]      # "contract" / "기안서" / ...
    canvas_id: Optional[str]        # set → load path; None → new-canvas path
    preset: dict                    # classified doc preset (scaffold/guidance/schema_version)

    # ---- reference binding (standard/baseline doc) ----
    anchor_pending: bool            # bind needs a user choice among candidates
    anchor_candidates: list[dict]   # [{document_id, name, score}] for the choice interrupt
    anchor_choice: dict             # resume payload: {document_id|index|skip}
    anchor_references: list[dict]   # bound anchor chunks (kind="anchor")
    anchor_context: Optional[str]   # labeled "기준 문서" context block

    # ---- grounding ----
    documents: list                 # retrieved chunks (transient, Document objects)
    references: list[dict]          # chunk dicts incl. chunk_id (persisted to Canvas.references)
    context: Optional[str]          # id-tagged context string for the draft prompt

    # ---- working canvas ----
    payload: dict                   # the working tree {metadata, sections, missing_terms}
    version_id: Optional[str]       # current persisted version
    canvas_payload: Optional[dict]  # serialized full canvas → stream_doc "canvas" event

    # ---- edit loop ----
    edit_op: Optional[dict]         # last resume payload {op, block_id?, feedback?, order?, ...}
    edit_error: Optional[str]       # reason the last op was rejected (surfaced on next interrupt)
    finalized: bool


def build_doc_input(
    instruction: str,
    team_ids: list[int],
    team_names: list[str],
    *,
    canvas_id: Optional[str] = None,
    canvas_type: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[int] = None,
    llm_name: Optional[str] = None,
) -> DocState:
    """Build the doc graph's initial input state."""
    return {
        "messages": [HumanMessage(content=instruction)],
        "team_ids": team_ids,
        "team_names": team_names,
        "session_id": session_id,
        "user_id": user_id,
        "llm_name": llm_name,
        "instruction": instruction,
        "canvas_type": canvas_type,
        "canvas_id": canvas_id,
        "finalized": False,
    }
