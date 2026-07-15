"""Draft node — LLM generates a canvas tree from grounded context, persists v1."""
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from maru_lang.constants import DOC_DRAFT_PROMPT, DOC_REGENERATE_PROMPT
from maru_lang.core.relation_db.models.auth import User
from maru_lang.core.relation_db.models.chat import Session
from maru_lang.graph.doc.constants import DEFAULT_DOC_LABEL, FREE_STRUCTURE
from maru_lang.graph.doc.parse import parse_json_object
from maru_lang.graph.doc.presets import get_preset
from maru_lang.graph.doc.state import DocState
from maru_lang.services.canvas import (
    assign_ids,
    create_canvas,
    extract_terms,
    index_references,
    iter_blocks,
    serialize_canvas,
    set_parties,
    write_version,
)


def _render_party_slots(parties: list[dict]) -> str:
    """Expected party slots (label + role) for the draft prompt; the model fills
    each slot's name from the request. Empty when the preset defines no parties."""
    if not parties:
        return "(해당 없음)"
    return "\n".join(f"- {p.get('label', '')} ({p.get('role', '')})" for p in parties)


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


def _nonempty_parties(parties: list[dict]) -> list[dict]:
    """Parties reduced to their filled fields (label + any non-blank value).

    Used to carry a user's already-entered 갑/을 names across a full regenerate so
    a redraft doesn't wipe them; blank fields are dropped so they don't clobber a
    name the model freshly extracts.
    """
    out = []
    for p in parties or []:
        if not isinstance(p, dict) or not p.get("label"):
            continue
        kept = {"label": p["label"]}
        kept.update({
            k: v for k, v in p.items()
            if k != "label" and isinstance(v, str) and v.strip()
        })
        if len(kept) > 1:  # something besides the label
            out.append(kept)
    return out


async def generate_canvas_tree(
    llm: BaseChatModel,
    state: DocState,
    *,
    feedback: str | None = None,
    prior_parties: list[dict] | None = None,
) -> tuple[dict, dict]:
    """Generate a normalized canvas payload from grounded state — no persistence.

    Shared by the initial draft and the `regenerate` op. `feedback`, when given,
    appends a "redo the whole doc addressing this" instruction to the draft prompt.
    `prior_parties` overlays already-filled party names last so a regenerate keeps
    the user's 갑/을 input. Returns (payload, meta) where meta carries
    title/canvas_type/schema_version/references for the caller to persist.
    """
    instruction = state.get("instruction") or ""
    # Bound standard/baseline doc (anchor) is prepended to the fuzzy RAG hits;
    # merged references back the per-block source_refs validation + audit.
    anchor_context = state.get("anchor_context")
    rag_context = state.get("context") or ""
    # anchor_only: RAG was skipped upstream (ground), so there's no fuzzy context
    # to blend. Reflect that intent in the prompt too — instruct the model to
    # follow the chosen standard(s) strictly, not merely "reference" them.
    if state.get("anchor_only") and anchor_context:
        anchor_context = (
            "[중요] 아래 기준 문서(표준 양식)만을 근거로 작성하라. 외부 지식이나 "
            "임의의 조항을 새로 만들지 말고, 표준의 구조·조항·표현을 요청에 맞게 "
            "충실히 따르라.\n\n" + anchor_context
        )
    context = "\n\n".join(c for c in (anchor_context, rag_context) if c) or "(참고 문서 없음)"
    references = (state.get("anchor_references") or []) + (state.get("references") or [])
    # Preset (from classify) seeds the scaffold/guidance/schema_version/parties.
    preset = state.get("preset") or get_preset(state.get("canvas_type")).to_state()
    canvas_type = preset.get("canvas_type") or state.get("canvas_type") or DEFAULT_DOC_LABEL

    preset_parties = preset.get("parties") or []
    prompt = DOC_DRAFT_PROMPT.format(
        doc_type=canvas_type,
        instruction=instruction,
        context=context,
        preset_label=preset.get("label", canvas_type),
        scaffold=preset.get("scaffold", FREE_STRUCTURE),
        party_slots=_render_party_slots(preset_parties),
        guidance=preset.get("guidance", ""),
    )
    # Full regenerate: append the user's feedback verbatim (not via .format(), so
    # braces in the feedback can't collide with the template's placeholders).
    if feedback:
        prompt = f"{prompt}\n\n{DOC_REGENERATE_PROMPT}\n{feedback}"
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    tree = parse_json_object(response.content or "")
    metadata = tree.get("metadata") or {}
    # Seed the preset's party slots (갑/을), then overlay any names the model
    # extracted from the request (matched by label). Unfilled slots stay blank
    # so the client's parties modal can still collect them.
    if preset_parties:
        extracted = metadata.get("parties") or []
        metadata["parties"] = [dict(p) for p in preset_parties]
        set_parties({"metadata": metadata}, extracted)
    # On regenerate, the user's already-entered party names win over both preset
    # blanks and a fresh model guess.
    if prior_parties:
        set_parties({"metadata": metadata}, _nonempty_parties(prior_parties))
    payload = assign_ids({
        "metadata": metadata,
        "sections": tree.get("sections") or [],
        "missing_terms": tree.get("missing_terms") or [],
    })
    _validate_sources(payload, index_references(references))
    # Derive missing_terms deterministically from the placeholder tokens the
    # draft actually wrote (canonicalizing them to {{label}}), instead of
    # trusting the LLM's parallel missing_terms list to stay in sync. This
    # links each term to its block(s) for inline fill-in and guarantees
    # set_terms can resolve every token later.
    extract_terms(payload)

    title = metadata.get("title") or instruction[:255] or None
    schema_version = preset.get("schema_version") or f"{canvas_type}.v1"
    return payload, {
        "title": title,
        "canvas_type": canvas_type,
        "schema_version": schema_version,
        "references": references,
    }


def make_draft_node(llm: BaseChatModel):
    """Create the initial-draft node."""

    async def draft_node(state: DocState) -> dict:
        instruction = state.get("instruction") or ""
        payload, meta = await generate_canvas_tree(llm, state)
        title = meta["title"]
        canvas_type = meta["canvas_type"]
        schema_version = meta["schema_version"]
        references = meta["references"]

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
