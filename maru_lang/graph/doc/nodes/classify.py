"""Classify node — pick a document preset (type) for the request, stage it in state.

Runs first on the new-canvas path. A client-supplied canvas_type wins (no LLM);
otherwise the LLM classifies among the registered presets, with a keyword fallback
on the raw request. The chosen preset is carried in state so ground/draft can use
its scaffold, guidance, schema_version, and default parties.
"""
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from maru_lang.constants import DOC_CLASSIFY_PROMPT
from maru_lang.graph.doc.presets import (
    DOC_PRESETS,
    get_preset,
    match_by_keyword,
    preset_choices_text,
)
from maru_lang.graph.doc.state import DocState


def _match_preset_id(text: str) -> str | None:
    """Find a known preset id mentioned in the LLM's classification output."""
    t = (text or "").strip().lower()
    return next((pid for pid in DOC_PRESETS if pid in t), None)


def make_classify_node(llm: BaseChatModel):
    async def classify_node(state: DocState) -> dict:
        # Client-specified type wins — skip the LLM call entirely.
        explicit = state.get("canvas_type")
        if explicit and explicit in DOC_PRESETS:
            preset = get_preset(explicit)
        else:
            instruction = state.get("instruction") or ""
            prompt = DOC_CLASSIFY_PROMPT.format(
                instruction=instruction, choices=preset_choices_text(),
            )
            try:
                resp = await llm.ainvoke([HumanMessage(content=prompt)])
                pid = _match_preset_id(resp.content or "")
            except Exception:
                pid = None
            preset = get_preset(pid or match_by_keyword(instruction))

        ps = preset.to_state()
        return {"preset": ps, "canvas_type": ps["canvas_type"]}

    return classify_node
