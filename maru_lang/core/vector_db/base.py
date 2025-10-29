from abc import ABC, abstractmethod
from typing import Any
from maru_lang.core.vector_db.retrieve_document import RetrieveDocument


class VectorDB(ABC):

    @abstractmethod
    def drop_collection(self) -> None:
        pass

    @abstractmethod
    def add_documents(self, documents: list[dict], store_text: bool = True) -> None:
        pass

    @abstractmethod
    def sync_documents(self) -> None:
        pass

    @abstractmethod
    def has_document(self, doc_id: str) -> bool:
        pass

    @abstractmethod
    def update_document(self, doc_id: str, new_doc_id: str, new_content: str, store_text: bool = True) -> None:
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
    def similarity_search(
        self,
        query: str,
        k: int,
        document_ids: list[str],
        **kwargs: dict[str, Any]
    ) -> list[RetrieveDocument]:
        pass

    @abstractmethod
    def bm25_search(
        self,
        query: str,
        k: int,
        document_ids: list[str],
        target_field: str | None = None,
    ) -> list[RetrieveDocument]:
        pass

    @abstractmethod
    def ensemble_search(
        self,
        query: str,
        k: int,
        cosine_k: int,
        document_ids: list[str],
        bm25_docs: list[RetrieveDocument] = [],
        cosine_weight: float = 0.7,
        bm25_weight: float = 0.3,
    ) -> list[RetrieveDocument]:
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
