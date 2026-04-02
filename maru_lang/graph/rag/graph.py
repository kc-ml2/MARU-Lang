"""RAG graph — intent → keyword → retrieve → evaluate → rerank → format.

Includes a retry loop: if evaluate decides results are insufficient,
keywords are regenerated and retrieval is retried (max 2 times).
"""
from typing import Optional

from langchain_core.documents.compressor import BaseDocumentCompressor
from langchain_core.language_models import BaseChatModel
from langchain_core.retrievers import BaseRetriever
from langgraph.graph import StateGraph, END

from maru_lang.graph.rag.state import RagState
from maru_lang.graph.rag.nodes import (
    make_intent_node,
    make_keyword_node,
    make_retrieve_node,
    make_evaluate_node,
    evaluate_route,
    make_rerank_node,
    format_node,
)


def create_rag_graph(
    retriever: BaseRetriever,
    llm: BaseChatModel,
    compressor: Optional[BaseDocumentCompressor] = None,
    evaluate_method: str = "rule",
):
    """Create the RAG pipeline graph.

    Args:
        retriever: BaseRetriever for document search.
        llm: LLM for intent/keyword extraction and optional evaluation.
        compressor: Optional reranker/compressor.
        evaluate_method: "rule" or "llm".

    Returns:
        Compiled StateGraph.
    """
    graph = StateGraph(RagState)

    graph.add_node("intent", make_intent_node(llm))
    graph.add_node("keywords", make_keyword_node(llm))
    graph.add_node("retrieve", make_retrieve_node(retriever))
    graph.add_node("evaluate", make_evaluate_node(
        method=evaluate_method,
        llm=llm if evaluate_method == "llm" else None,
    ))
    graph.add_node("rerank", make_rerank_node(compressor))
    graph.add_node("format", format_node)

    graph.set_entry_point("intent")
    graph.add_edge("intent", "keywords")
    graph.add_edge("keywords", "retrieve")
    graph.add_edge("retrieve", "evaluate")

    graph.add_conditional_edges(
        "evaluate",
        evaluate_route,
        {"rerank": "rerank", "retry": "keywords"},
    )
    graph.add_edge("rerank", "format")
    graph.add_edge("format", END)

    return graph.compile()


async def run_rag(
    query: str,
    team_ids: list[int],
    *,
    retriever: BaseRetriever,
    llm: BaseChatModel,
    compressor: Optional[BaseDocumentCompressor] = None,
    evaluate_method: str = "rule",
) -> str:
    """Run the RAG pipeline and return formatted results."""
    rag_graph = create_rag_graph(retriever, llm, compressor, evaluate_method)

    result = await rag_graph.ainvoke({
        "query": query,
        "rewritten_query": "",
        "keywords": [],
        "documents": [],
        "result": "",
        "team_ids": team_ids,
        "retry_count": 0,
        "messages": [],
    })

    return result["result"]
