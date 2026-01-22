from abc import ABC, abstractmethod
from typing import Any
from maru_lang.core.vector_db.retrieve_document import RetrieveDocument


class VectorDB(ABC):

    @abstractmethod
    def drop_collection(self) -> None:
        pass

    @abstractmethod
    def add_documents(self, documents: list[dict], embeddings: list[list[float]]) -> None:
        pass

    @abstractmethod
    def upsert_documents(self, documents: list[dict], embeddings: list[list[float]]) -> None:
        """Add or update documents in VectorDB.

        Args:
            documents: List of documents with id, content, metadata
            embeddings: List of embedding vectors
        """
        pass

    @abstractmethod
    def get_chunk_ids_by_document_id(self, document_id: str) -> list[str]:
        """Get all chunk IDs for a document.

        Args:
            document_id: Document ID

        Returns:
            List of chunk IDs
        """
        pass

    @abstractmethod
    def delete_chunks_by_ids(self, chunk_ids: list[str]) -> int:
        """Delete chunks by their IDs.

        Args:
            chunk_ids: List of chunk IDs to delete

        Returns:
            Number of deleted chunks
        """
        pass

    @abstractmethod
    def sync_documents(self) -> None:
        pass

    @abstractmethod
    def has_document(self, doc_id: str) -> bool:
        pass

    @abstractmethod
    def update_document(self, doc_id: str, new_doc_id: str, new_content: str) -> None:
        pass

    @abstractmethod
    def delete_document(self, doc_id: str) -> None:
        pass

    @abstractmethod
    def delete_all_chunks_by_document_id(self, document_id: str) -> int:
        """문서 ID로 해당 문서의 모든 청크를 삭제합니다.
        
        Args:
            document_id: 삭제할 문서의 ID
            
        Returns:
            삭제된 청크의 개수
        """
        pass

    @abstractmethod
    def count_documents(self) -> int:
        pass

    @abstractmethod
    def get_all_metadata(self) -> list[dict]:
        pass

    @abstractmethod
    def get_documents(self, document_ids: list[str]) -> list[RetrieveDocument]:
        pass

    @abstractmethod
    def get_all_documents(
        self,
        team_ids: list[int]
    ) -> list[RetrieveDocument]:
        """
        Get all documents from VectorDB filtered by team IDs

        Args:
            team_ids: List of Team IDs to filter

        Returns:
            List of documents filtered by teams
        """
        pass

    @abstractmethod
    def similarity_search(
        self,
        query_embedding: list[float],
        k: int,
        team_ids: list[int],
        **kwargs: dict[str, Any]
    ) -> list[RetrieveDocument]:
        """
        Vector similarity search using query embedding

        Args:
            query_embedding: Query embedding vector
            k: Number of results to return
            team_ids: List of Team IDs to filter
            **kwargs: Additional search parameters

        Returns:
            List of retrieved documents
        """
        pass

    @abstractmethod
    def hybrid_search(
        self,
        query_text: str,
        query_embedding: list[float],
        k: int,
        team_ids: list[int],
        **kwargs: dict[str, Any]
    ) -> list[RetrieveDocument]:
        """
        Hybrid search combining full-text search and vector similarity

        Args:
            query_text: Query text for full-text/BM25 search
            query_embedding: Query embedding vector for similarity search
            k: Number of results to return
            team_ids: List of Team IDs to filter
            **kwargs: Additional search parameters
                - alpha: Weight for combining scores (0.0 = full-text only, 1.0 = vector only)

        Returns:
            List of retrieved documents with combined scores
        """
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """
        VectorDB 헬스체크 (연결 및 접근 가능 여부 확인)

        Returns:
            bool: 헬스체크 통과 여부

        Raises:
            Exception: 헬스체크 실패 시 상세 에러
        """
        pass
