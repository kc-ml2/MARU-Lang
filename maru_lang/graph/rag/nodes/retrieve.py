"""Retrieve node — search VectorDB with keywords."""
from maru_lang.graph.rag.retriever import VectorRetriever
from maru_lang.graph.rag.state import RagState


def make_retrieve_node(retriever: VectorRetriever):
    """Create a retrieve node bound to the given VectorRetriever."""

    async def retrieve_node(state: RagState) -> dict:
        scoped_retriever = retriever.model_copy(update={
            "team_ids": state["team_ids"],
            "exclude_ids": state.get("excluded_doc_ids", []),
        })

        search_query = " ".join(state["keywords"]) if state["keywords"] else state["query"]
        docs = await scoped_retriever.ainvoke(search_query)

        return {
            "documents": docs,
            "rag_log": state.get("rag_log", []) + [f"Retrieved: {len(docs)} documents"],
        }

    return retrieve_node
