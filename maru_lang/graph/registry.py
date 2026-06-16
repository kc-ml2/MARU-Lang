"""Graph registry — the set of selectable graphs and their descriptions.

The graph_router picks one of these (restricted to a team's accessible set) per
user request. Each graph is built from shared node factories, so overlapping
nodes are reused without a monolithic supergraph.
"""
from dataclasses import dataclass
from typing import Callable

from maru_lang.graph.rag.graph import create_rag_graph


@dataclass(frozen=True)
class GraphSpec:
    id: str
    description: str          # used by the router to classify the request
    factory: Callable         # (model=None, checkpointer=None) -> compiled graph


GRAPH_REGISTRY: dict[str, GraphSpec] = {
    "chat": GraphSpec(
        id="chat",
        description="내부 팀 문서를 검색하거나 일반 대화로 사용자 질문에 답한다 (기본 그래프).",
        factory=create_rag_graph,
    ),
}


# Granted to a team whose allowed_graphs is empty. Adding a new graph to the
# registry does NOT auto-expose it to every team — it must be opted into per
# team via Team.allowed_graphs.
DEFAULT_GRAPH_ID = "chat"


def registry_graph_ids() -> list[str]:
    """All registered graph ids (stable order)."""
    return list(GRAPH_REGISTRY.keys())
