"""Graph registry — the set of selectable graphs and their descriptions.

The graph_router picks one of these (restricted to a team's accessible set) per
user request. Each graph is built from shared node factories, so overlapping
nodes are reused without a monolithic supergraph.
"""
from dataclasses import dataclass, field
from typing import Callable

from maru_lang.graph.rag.graph import create_rag_graph, stream_rag
from maru_lang.graph.doc.graph import create_doc_graph, stream_doc


@dataclass(frozen=True)
class GraphSpec:
    """A selectable graph + how it interprets an inbound chat message.

    The chat endpoint stays graph-agnostic: per-graph payload parsing and routing
    claims live here so adding a graph means editing only this registry.
    """
    id: str
    description: str               # used by the router (L1) to classify the request
    factory: Callable              # (model=None, checkpointer=None) -> compiled graph
    streamer: Callable | None = None  # (message, team_ids, team_names, *, graph, config, **kw) -> AsyncIterator[(type, payload)]
    # Does this graph force-handle the inbound `message` payload, bypassing L1
    # routing? (e.g. doc claims a payload carrying an existing canvas_id.)
    claims: Callable[[dict], bool] = field(default=lambda data: False)
    # Per-message inputs this graph's streamer needs, extracted from the payload
    # (carried for the whole turn and reused on resume).
    extract_inputs: Callable[[dict], dict] = field(default=lambda data: {})


GRAPH_REGISTRY: dict[str, GraphSpec] = {
    "chat": GraphSpec(
        id="chat",
        description="내부 팀 문서를 검색하거나 일반 대화로 사용자 질문에 답한다 (기본 그래프).",
        factory=create_rag_graph,
        streamer=stream_rag,
    ),
    "doc": GraphSpec(
        id="doc",
        description=(
            "내부 팀 문서를 근거로 계약서·공문·이메일·보고서 등 새 문서의 초안을 작성하고, "
            "블록 단위로 사용자 피드백을 받아 수정한다."
        ),
        factory=create_doc_graph,
        streamer=stream_doc,
        # 진행 중 canvas를 편집하는 후속 메시지는 항상 doc가 처리(L1 우회).
        claims=lambda data: bool(data.get("canvas_id")),
        extract_inputs=lambda data: {
            "canvas_id": data.get("canvas_id"),
            "canvas_type": data.get("canvas_type"),
        },
    ),
}


# Granted to a team whose allowed_graphs is empty (the default state). Adding a
# new graph to the registry does NOT auto-expose it — a team opts in by setting
# allowed_graphs (e.g. via `maru run` → /graphs). An empty allowlist falls back
# to this default set.
DEFAULT_GRAPH_IDS = ["chat"]


def registry_graph_ids() -> list[str]:
    """All registered graph ids (stable order)."""
    return list(GRAPH_REGISTRY.keys())


def registerable_graphs() -> list[dict]:
    """Registered graphs as {id, description} (for per-team graph configuration)."""
    return [{"id": gid, "description": spec.description} for gid, spec in GRAPH_REGISTRY.items()]
