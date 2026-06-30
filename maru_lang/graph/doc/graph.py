"""Document-authoring (doc) graph: ground → draft → interrupt-driven edits.

A second graph alongside the RAG chat graph. It drafts a structured document (a
*canvas* tree: sections → blocks) from internal team docs, returns it whole, and
loops over edits via LangGraph interrupts until the user finalizes. The DB
(Canvas/CanvasVersion, event-sourced snapshots) is the durable source of truth so
a dropped connection can reload the head version and resume.

Topology
--------
    entry_router ──"load"(canvas_id)──► load_canvas ─────────────────────────────┐
        │ "new"                                                                   │
        ▼          ┌─clear/none─────────────────────────┐                        ▼
      classify → bind_reference                          ▼                  await_edit ◄─┐
                   └─ambiguous─► await_anchor_choice → resolve_anchor → ground → draft ──┘
                                                                  │ interrupt│
                                       (resume = {op,...})         ▼         │
                                                  ┌──── apply_edit ──────────┘
                                                  │ op=="finalize"
                                                  ▼
                                              finalize ─► END
"""
from typing import AsyncIterator, Union

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END
from langgraph.types import Command

from maru_lang.configs import get_config
from maru_lang.core.llm import get_model_with_fallbacks
from maru_lang.graph.doc.state import DocState, build_doc_input
from maru_lang.graph.doc.nodes import (
    entry_router,
    make_load_canvas_node,
    post_load_route,
    make_classify_node,
    make_bind_reference_node,
    anchor_route,
    await_anchor_choice_node,
    make_resolve_anchor_node,
    make_ground_node,
    make_draft_node,
    await_edit_node,
    apply_edit_route,
    make_apply_edit_node,
    make_finalize_node,
)
from maru_lang.core.vector_db import get_vector_db
from maru_lang.graph.rag.retriever import build_retriever
from maru_lang.graph.rag.reranker import build_compressor


def create_doc_graph(model: BaseChatModel | None = None, checkpointer=None):
    """Build and compile the document-authoring graph.

    Reads config + LLM internally (like create_rag_graph). The compiled graph
    pauses at `await_edit` (interrupt) between edits; resume with an edit command.
    """
    if model is None:
        model = get_model_with_fallbacks()
        if model is None:
            raise RuntimeError("No LLM model available. Check llms config.")

    cfg = get_config()
    retriever = build_retriever(cfg)
    compressor = build_compressor(cfg)
    vdb = get_vector_db()

    graph = StateGraph(DocState)

    graph.add_node("load_canvas", make_load_canvas_node())
    graph.add_node("classify", make_classify_node(model))
    graph.add_node("bind_reference", make_bind_reference_node(vdb))
    graph.add_node("await_anchor_choice", await_anchor_choice_node)
    graph.add_node("resolve_anchor", make_resolve_anchor_node(vdb))
    graph.add_node("ground", make_ground_node(retriever, compressor))
    graph.add_node("draft", make_draft_node(model))
    graph.add_node("await_edit", await_edit_node)
    graph.add_node("apply_edit", make_apply_edit_node(model))
    graph.add_node("finalize", make_finalize_node())

    graph.set_conditional_entry_point(
        entry_router,
        {"load_canvas": "load_canvas", "classify": "classify"},
    )
    graph.add_edge("classify", "bind_reference")
    graph.add_conditional_edges(
        "bind_reference", anchor_route,
        {"await_anchor_choice": "await_anchor_choice", "ground": "ground"},
    )
    graph.add_edge("await_anchor_choice", "resolve_anchor")
    graph.add_edge("resolve_anchor", "ground")
    graph.add_edge("ground", "draft")
    graph.add_edge("draft", "await_edit")
    # A finalized/unauthorized load is read-only → END; otherwise enter the edit loop.
    graph.add_conditional_edges(
        "load_canvas", post_load_route,
        {"await_edit": "await_edit", "end": END},
    )
    graph.add_conditional_edges(
        "await_edit", apply_edit_route,
        {"apply_edit": "apply_edit", "finalize": "finalize"},
    )
    graph.add_edge("apply_edit", "await_edit")
    graph.add_edge("finalize", END)

    if checkpointer is None:
        checkpointer = MemorySaver()

    return graph.compile(checkpointer=checkpointer)


async def stream_doc(
    message: Union[str, Command],
    team_ids: list[int],
    team_names: list[str],
    *,
    graph,
    config: dict | None = None,
    canvas_id: str | None = None,
    canvas_type: str | None = None,
    session_id: str | None = None,
    user_id: int | None = None,
    llm_name: str | None = None,
    **_ignored,
) -> AsyncIterator[tuple[str, object]]:
    """Stream the doc graph as (event_type, content) tuples.

    Events:
        - ("canvas", {...}): the current document (initial draft or post-edit),
          the full serialized canvas (envelope + tree).
        - ("interrupt", value): paused at await_edit, awaiting an edit command.

    `message` is the authoring instruction string, or Command(resume=op) to resume.
    Shares stream_rag's keyword surface (extra kwargs ignored) so the two are
    interchangeable from the registry-driven dispatch.
    """
    if isinstance(message, Command):
        input_state = message
    else:
        input_state = build_doc_input(
            message, team_ids, team_names,
            canvas_id=canvas_id, canvas_type=canvas_type,
            session_id=session_id, user_id=user_id, llm_name=llm_name,
        )

    async for mode, event in graph.astream(
        input_state, config=config, stream_mode=["updates"],
    ):
        if mode == "updates":
            for _node, state_update in event.items():
                if not isinstance(state_update, dict):
                    continue
                payload = state_update.get("canvas_payload")
                if payload:
                    yield "canvas", payload

    # Surface the pending interrupt (paused at await_edit for the next op).
    snapshot = await graph.aget_state(config)
    for task in snapshot.tasks:
        if task.interrupts:
            yield "interrupt", task.interrupts[0].value
            break
