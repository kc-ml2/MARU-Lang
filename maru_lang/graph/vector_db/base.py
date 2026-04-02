"""VectorDB abstract base class."""
from abc import ABC, abstractmethod
from typing import Any

from langchain_core.documents import Document


class VectorDB(ABC):

    @abstractmethod
    def drop_collection(self) -> None:
        pass

    @abstractmethod
    def add_documents(self, documents: list[dict], embeddings: list[list[float]]) -> None:
        pass

    @abstractmethod
    def upsert_documents(self, documents: list[dict], embeddings: list[list[float]]) -> None:
        pass

    @abstractmethod
    def get_chunk_ids_by_document_id(self, document_id: str) -> list[str]:
        pass

    @abstractmethod
    def delete_chunks_by_ids(self, chunk_ids: list[str]) -> int:
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
        pass

    @abstractmethod
    def count_documents(self) -> int:
        pass

    @abstractmethod
    def get_all_metadata(self) -> list[dict]:
        pass

    @abstractmethod
    def get_documents(self, document_ids: list[str]) -> list[Document]:
        pass

    @abstractmethod
    def get_all_documents(self, team_ids: list[int]) -> list[Document]:
        pass

    @abstractmethod
    def similarity_search(
        self,
        query_embedding: list[float],
        k: int,
        team_ids: list[int],
        **kwargs: dict[str, Any],
    ) -> list[Document]:
        pass

    @abstractmethod
    def hybrid_search(
        self,
        query_text: str,
        query_embedding: list[float],
        k: int,
        team_ids: list[int],
        **kwargs: dict[str, Any],
    ) -> list[Document]:
        pass

    @abstractmethod
    def health_check(self) -> bool:
        pass
