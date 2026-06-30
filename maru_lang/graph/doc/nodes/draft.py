"""Draft node — LLM generates a canvas tree from grounded context, persists v1."""
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from maru_lang.constants import DOC_DRAFT_PROMPT
from maru_lang.core.relation_db.models.auth import User
from maru_lang.core.relation_db.models.chat import Session
from maru_lang.graph.doc.nodes._parse import parse_json_object
from maru_lang.graph.doc.presets import get_preset
from maru_lang.graph.doc.state import DocState
from maru_lang.services.canvas import (
    assign_ids,
    create_canvas,
    index_references,
    iter_blocks,
    serialize_canvas,
    write_version,
)


def _validate_sources(payload: dict, ref_index: dict[str, dict]) -> None:
    """Replace each block's source_refs (chunk-id strings) with enriched ref dicts,
    dropping hallucinated ids not in the retrieved set (mutates in place)."""
    for _section, block in iter_blocks(payload):
        enriched = []
        for cid in block.get("source_refs") or []:
            ref = ref_index.get(str(cid))
            if ref is None:
                continue
            enriched.append({
                "chunk_id": ref["chunk_id"],
                "document_id": ref.get("document_id"),
                "document_name": ref.get("document_name"),
                "score": ref.get("score"),
            })
        block["source_refs"] = enriched


def make_draft_node(llm: BaseChatModel):
    """Create the initial-draft node."""

    async def draft_node(state: DocState) -> dict:
        instruction = state.get("instruction") or ""
        # Bound standard/baseline doc (anchor) is prepended to the fuzzy RAG hits;
        # merged references back the per-block source_refs validation + audit.
        anchor_context = state.get("anchor_context")
        rag_context = state.get("context") or ""
        context = "\n\n".join(c for c in (anchor_context, rag_context) if c) or "(참고 문서 없음)"
        references = (state.get("anchor_references") or []) + (state.get("references") or [])
        # Preset (from classify) seeds the scaffold/guidance/schema_version/parties.
        preset = state.get("preset") or get_preset(state.get("canvas_type")).to_state()
        canvas_type = preset.get("canvas_type") or state.get("canvas_type") or "문서"

        prompt = DOC_DRAFT_PROMPT.format(
            doc_type=canvas_type,
            instruction=instruction,
            context=context,
            preset_label=preset.get("label", canvas_type),
            scaffold=preset.get("scaffold", "(자유 구조)"),
            guidance=preset.get("guidance", ""),
        )
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        tree = parse_json_object(response.content or "")
        metadata = tree.get("metadata") or {}
        # Seed default parties (e.g. 갑/을) when the model didn't supply any.
        if not metadata.get("parties") and preset.get("parties"):
            metadata["parties"] = preset["parties"]
        payload = assign_ids({
            "metadata": metadata,
            "sections": tree.get("sections") or [],
            "missing_terms": tree.get("missing_terms") or [],
        })
        _validate_sources(payload, index_references(references))

        title = metadata.get("title") or instruction[:255] or None
        schema_version = preset.get("schema_version") or f"{canvas_type}.v1"

        # Persist only when we have an owning user (mirrors summarize gating); without
        # a user_id (tests/CLI smoke) the graph still surfaces the in-memory canvas.
        user_id = state.get("user_id")
        if user_id:
            user = await User.get_or_none(id=user_id)
            session = (
                await Session.get_or_none(id=state["session_id"])
                if state.get("session_id") else None
            )
            if user is not None:
                canvas = await create_canvas(
                    user,
                    session=session,
                    canvas_type=canvas_type,
                    schema_version=schema_version,
                    title=title,
                    instruction=instruction,
                    references=references,
                )
                version = await write_version(canvas, payload, base_version_id=None, op=None)
                return {
                    "canvas_id": canvas.id,
                    "version_id": version.id,
                    "payload": payload,
                    "canvas_payload": serialize_canvas(canvas, version),
                }

        # No-DB fallback: surface an in-memory canvas (no persisted ids).
        canvas_payload = {
            "schema_version": schema_version,
            "canvas_type": canvas_type,
            "canvas_id": None,
            "version_id": None,
            "base_version_id": None,
            "status": "drafting",
            "title": title,
            "metadata": payload.get("metadata", {}),
            "sections": payload.get("sections", []),
            "missing_terms": payload.get("missing_terms", []),
        }
        return {"payload": payload, "canvas_payload": canvas_payload}

    return draft_node
