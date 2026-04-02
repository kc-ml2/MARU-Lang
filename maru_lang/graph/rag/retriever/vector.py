"""VectorDB-based retriever (LangChain BaseRetriever).

Supports vector and hybrid search. Config-free: all parameters
are injected at construction time.
"""
import asyncio
import logging
from typing import Optional

from langchain_core.callbacks import CallbackManagerForRetrieverRun, AsyncCallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from pydantic import Field, PrivateAttr

from maru_lang.core.vector_db import get_vector_db
from maru_lang.core.vector_db.base import VectorDB
from maru_lang.graph.ingest.embedder import get_embeddings

logger = logging.getLogger(__name__)


class VectorRetriever(BaseRetriever):
    """LangChain-compatible retriever backed by VectorDB.

    All parameters are set at construction time — no config dependency.
    """

    team_ids: list[int] = Field(default_factory=list)
    top_k: int = 5
    search_method: str = "vector"

    _vdb: VectorDB = PrivateAttr()
    _embeddings: Embeddings = PrivateAttr()

    def __init__(
        self,
        *,
        vdb: Optional[VectorDB] = None,
        embeddings: Optional[Embeddings] = None,
        embedding_model: str = "BAAI/bge-m3",
        embedding_device: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._vdb = vdb or get_vector_db()
        self._embeddings = embeddings or get_embeddings(
            model_name=embedding_model,
            device=embedding_device,
        )

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        if not self.team_ids:
            logger.warning("No team_ids provided - refusing to search all documents")
            return []

        query_embedding = self._embeddings.embed_query(query)

        try:
            if self.search_method == "hybrid":
                return self._vdb.hybrid_search(
                    query, query_embedding, self.top_k, self.team_ids
                )
            else:
                return self._vdb.similarity_search(
                    query_embedding, self.top_k, self.team_ids
                )
        except Exception as e:
            logger.error(f"VDB search error: {e}")
            return []

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: AsyncCallbackManagerForRetrieverRun,
    ) -> list[Document]:
        if not self.team_ids:
            logger.warning("No team_ids provided - refusing to search all documents")
            return []

        query_embedding = self._embeddings.embed_query(query)

        try:
            if self.search_method == "hybrid":
                return await asyncio.to_thread(
                    self._vdb.hybrid_search,
                    query, query_embedding, self.top_k, self.team_ids,
                )
            else:
                return await asyncio.to_thread(
                    self._vdb.similarity_search,
                    query_embedding, self.top_k, self.team_ids,
                )
        except Exception as e:
            logger.error(f"VDB search error: {e}")
            return []
