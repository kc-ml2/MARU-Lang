"""Graph router — pick which graph handles a request (within a team's access).

This is the L1 router (which graph), above each graph's internal routing.
"""
from langchain_core.language_models import BaseChatModel

from maru_lang.constants import GRAPH_ROUTER_PROMPT
from maru_lang.graph.registry import GRAPH_REGISTRY


async def select_graph(
    message: str,
    graph_ids: list[str],
    model: BaseChatModel | None = None,
) -> str:
    """Return the graph id best suited to `message`, among `graph_ids`.

    - 0 accessible graphs → ValueError.
    - 1 accessible graph → return it (no LLM call).
    - else → LLM classifies; on failure/unparseable, fall back to the first id.
    """
    ids = [gid for gid in graph_ids if gid in GRAPH_REGISTRY]
    if not ids:
        raise ValueError("No accessible graphs to route to.")
    if len(ids) == 1 or model is None:
        return ids[0]

    options = "\n".join(f"- {gid}: {GRAPH_REGISTRY[gid].description}" for gid in ids)
    try:
        response = await model.ainvoke(GRAPH_ROUTER_PROMPT.format(options=options, message=message))
        choice = (response.content or "").strip().lower()
    except Exception:
        return ids[0]

    for gid in ids:
        if gid.lower() == choice or gid.lower() in choice:
            return gid
    return ids[0]  # unparseable → safe default
