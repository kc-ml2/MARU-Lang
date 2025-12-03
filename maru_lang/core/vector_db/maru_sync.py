"""
MaruSync VectorDB - Client-side VectorDB for MaruSync
"""
import asyncio
from typing import Any
from maru_lang.core.vector_db.base import VectorDB
from maru_lang.core.vector_db.retrieve_document import RetrieveDocument
from maru_lang.core.sync import sync_request
from maru_lang.dependencies.sync import get_sync_manager


class MaruSyncVectorDB(VectorDB):
    """
    MaruSync VectorDB implementation that delegates operations to connected clients.

    This VectorDB doesn't store data on the server. Instead, it forwards all operations
    to the client (Electron app) via WebSocket using the sync protocol.

    Only similarity_search is implemented - all other operations are not needed for MaruSync.
    """

    def __init__(self, client_id: int):
        """
        Initialize MaruSync VectorDB

        Args:
            client_id: The client ID who owns this VectorDB instance
        """
        self.client_id = client_id

    # ========== Not Needed for MaruSync ==========

    def drop_collection(self) -> None:
        """Not needed for MaruSync"""
        raise NotImplementedError("MaruSync doesn't support drop_collection")

    def add_documents(
        self,
        documents: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        """Not needed for MaruSync - use sync_request directly in pipeline"""
        raise NotImplementedError("MaruSync doesn't support add_documents - use sync_request in pipeline")

    def sync_documents(self) -> None:
        """Not needed for MaruSync"""
        pass

    def has_document(self, doc_id: str) -> bool:
        """Not needed for MaruSync"""
        raise NotImplementedError("MaruSync doesn't support has_document")

    def update_document(self, doc_id: str, new_doc_id: str, new_content: str) -> None:
        """Not needed for MaruSync"""
        raise NotImplementedError("MaruSync doesn't support update_document")

    def delete_document(self, doc_id: str) -> None:
        """Not needed for MaruSync"""
        raise NotImplementedError("MaruSync doesn't support delete_document")

    def delete_all_chunks_by_document_id(self, document_id: str) -> int:
        """Not needed for MaruSync - use sync_request directly in pipeline"""
        raise NotImplementedError("MaruSync doesn't support delete_all_chunks_by_document_id - use sync_request in pipeline")

    def count_documents(self) -> int:
        """Not needed for MaruSync"""
        raise NotImplementedError("MaruSync doesn't support count_documents")

    def get_all_metadata(self) -> list[dict]:
        """Not needed for MaruSync"""
        raise NotImplementedError("MaruSync doesn't support get_all_metadata")

    def get_documents(self, document_ids: list[str]) -> list[RetrieveDocument]:
        """Not needed for MaruSync"""
        raise NotImplementedError("MaruSync doesn't support get_documents")

    def get_all_documents(
        self,
        version_ids: list[str]
    ) -> list[RetrieveDocument]:
        """Not needed for MaruSync"""
        raise NotImplementedError("MaruSync doesn't support get_all_documents")

    # ========== Core Implementation ==========

    async def similarity_search(
        self,
        query_embedding: list[float],
        k: int,
        version_ids: list[str],
        **kwargs: dict[str, Any]
    ) -> list[RetrieveDocument]:
        """
        Perform similarity search on client side VectorDB

        Args:
            query_embedding: Query embedding vector
            k: Number of results to return
            version_ids: List of version IDs to filter (required)
            **kwargs: Additional search parameters

        Returns:
            List of retrieved documents
        """
        # Run async sync_request in sync context
        try:
            response = await sync_request(
                    user_id=self.client_id,
                    action="similarity_search",
                    data={
                        "query_embedding": query_embedding,
                        "k": k,
                        "version_ids": version_ids,
                        **kwargs
                    },
                    timeout=30.0
                )            
            # Parse response and convert to RetrieveDocument objects
            results = response.get("results", [])

        except Exception as e:
            print(f"❌ Similarity search failed: {e}")
            return []

        return [
            RetrieveDocument(
                id=doc["id"],
                page_content=doc["content"],
                metadata=doc["metadata"]
            )
            for doc in results
        ]

    async def hybrid_search(
        self,
        query_text: str,
        query_embedding: list[float],
        k: int,
        version_ids: list[str],
        **kwargs: dict[str, Any]
    ) -> list[RetrieveDocument]:
        """
        Perform hybrid search on client side VectorDB

        Args:
            query_text: Query text for full-text search
            query_embedding: Query embedding vector for similarity search
            k: Number of results to return
            version_ids: List of version IDs to filter (required)
            **kwargs: Additional search parameters

        Returns:
            List of retrieved documents with hybrid scores
        """
        try:
            response = await sync_request(
                user_id=self.client_id,
                action="hybrid_search",
                data={
                    "query_text": query_text,
                    "query_embedding": query_embedding,
                    "k": k,
                    "version_ids": version_ids,
                    **kwargs
                },
                timeout=30.0
            )
            results = response.get("results", [])
        except Exception as e:
            print(f"❌ Hybrid search failed: {e}")
            return []

        return [
            RetrieveDocument(
                id=doc["id"],
                page_content=doc["content"],
                metadata=doc["metadata"]
            )
            for doc in results
        ]
         
    def health_check(self) -> bool:
        """Not needed for MaruSync"""
        raise NotImplementedError("MaruSync doesn't support health_check")
