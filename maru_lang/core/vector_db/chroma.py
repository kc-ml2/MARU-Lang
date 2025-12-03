import chromadb
import asyncio
from typing import Any
from chromadb.api.models.Collection import Collection
from maru_lang.core.vector_db.base import VectorDB
from maru_lang.core.vector_db.retrieve_document import RetrieveDocument
from maru_lang.configs.system_config import get_system_config

config = get_system_config()


class ChromaVectorDB(VectorDB):
    def __init__(
        self,
        persist_dir: str,
        collection_name: str,
    ):
        self.persist_dir: str = persist_dir
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection: Collection = self.client.get_or_create_collection(
            name=collection_name
        )

    def drop_collection(self) -> None:
        """
        컬렉션 삭제
        """
        self.client.delete_collection(self.collection.name)
        self.collection = None

    def add_documents(
        self,
        documents: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        """
        문서를 VectorDB에 추가 (ChromaDB 배치 크기 제한을 자동 처리)

        Args:
            documents: 문서 리스트 (id, content, metadata 포함)
            embeddings: 임베딩 벡터 리스트 (외부에서 생성)
        """
        # ChromaDB 내부 배치 크기 제한 (5461) 고려
        CHROMA_MAX_BATCH_SIZE = 5000  # 안전 마진

        contents = [doc["content"] for doc in documents]
        ids = [doc["id"] for doc in documents]
        metadatas = [doc["metadata"] for doc in documents]

        # 배치 크기가 제한을 초과하면 자동 분할
        total_items = len(documents)
        for i in range(0, total_items, CHROMA_MAX_BATCH_SIZE):
            end_idx = min(i + CHROMA_MAX_BATCH_SIZE, total_items)

            self.collection.add(
                documents=contents[i:end_idx],
                embeddings=embeddings[i:end_idx],
                ids=ids[i:end_idx],
                metadatas=metadatas[i:end_idx]
            )

    def sync_documents(self) -> None:
        # Chroma는 일반적으로 flush 필요 없음
        pass

    def has_document(self, doc_id: str) -> bool:
        try:
            result = self.collection.get(ids=[doc_id])
            return len(result["ids"]) > 0
        except Exception:
            return False

    def update_document(
        self,
        doc_id: str,
        new_doc_id: str,
        new_content: str,
        embedding: list[float],
    ) -> None:
        """
        문서 업데이트

        Args:
            doc_id: 기존 문서 ID
            new_doc_id: 새 문서 ID
            new_content: 새 문서 내용
            embedding: 새 임베딩 벡터 (외부에서 생성)
        """
        try:
            existing = self.collection.get(ids=[doc_id])
            if not existing["ids"]:
                raise ValueError(f"Document with id={doc_id} not found")

            old_metadata = existing["metadatas"][0]

            # 먼저 삭제
            self.collection.delete(ids=[doc_id])
            # 다시 추가
            self.collection.add(
                documents=[new_content],
                embeddings=[embedding],
                ids=[new_doc_id],
                metadatas=[old_metadata]
            )
        except Exception as e:
            raise RuntimeError(f"Failed to update document {doc_id}: {str(e)}")

    def delete_document(self, doc_id: str) -> None:
        self.collection.delete(ids=[doc_id])

    def delete_all_chunks_by_document_id(self, document_id: str) -> int:
        """문서 ID로 해당 문서의 모든 청크를 삭제합니다."""
        try:
            # 해당 document_id를 가진 모든 청크 조회
            results = self.collection.get(
                where={"document_id": {"$eq": document_id}},
                include=["metadatas"]
            )
            
            chunk_ids = results["ids"]
            if not chunk_ids:
                return 0
            
            # 모든 청크 삭제
            self.collection.delete(ids=chunk_ids)
            return len(chunk_ids)
            
        except Exception as e:
            print(f"❌ 벡터DB에서 문서 청크 삭제 실패: {e}")
            return 0

    def count_documents(self) -> int:
        return len(self.collection.get()["ids"])  # 예시: ChromaDB의 문서 ID 개수

    def get_all_metadata(self) -> list[dict]:
        """
        전체 메타데이터 가져오기
        """
        return self.collection.get(include=["metadatas"])["metadatas"]

    def get_documents(self, document_ids: list[str]) -> list[RetrieveDocument]:
        results = self.collection.get(
            where={"document_id": {"$in": document_ids}})

        docs = results["documents"]
        ids = results["ids"]
        metadatas = results["metadatas"]

        return [
            RetrieveDocument(
                id=doc_id,
                page_content=doc,
                metadata=metadata
            )
            for doc_id, doc, metadata in zip(ids, docs, metadatas)
        ]

    def get_all_documents(
        self,
        version_ids: list[str]
    ) -> list[RetrieveDocument]:
        """
        Get all documents from VectorDB filtered by version IDs

        Args:
            version_ids: List of version IDs to filter (required)

        Returns:
            List of documents filtered by version
        """
        # Build filter with required version_ids
        filter_where = {"version_id": {"$in": version_ids}}

        # Get all documents with filter
        results = self.collection.get(
            where=filter_where,
            include=["documents", "metadatas"]
        )

        docs = results["documents"]
        ids = results["ids"]
        metadatas = results["metadatas"]

        return [
            RetrieveDocument(
                id=doc_id,
                page_content=doc,
                metadata=metadata
            )
            for doc_id, doc, metadata in zip(ids, docs, metadatas)
        ]

    def similarity_search(
        self,
        query_embedding: list[float],
        k: int,
        version_ids: list[str],
        **kwargs: dict[str, Any],
    ) -> list[RetrieveDocument]:
        """
        유사도 검색 (버전 기반)

        Args:
            query_embedding: 쿼리 임베딩 벡터 (외부에서 생성)
            k: 반환할 결과 개수
            version_ids: 버전 ID 필터 (required)
        """
        # 버전 필터 생성 (required)
        filter = {"version_id": {"$in": version_ids}}

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            where=filter
        )

        docs = results["documents"][0]
        ids = results["ids"][0]
        metadatas = results["metadatas"][0]
        distances = results["distances"][0]

        return [
            RetrieveDocument(
                id=doc_id,
                page_content=doc,
                metadata={**metadata, "score": 1 - distance}
            )
            for doc_id, doc, metadata, distance in zip(ids, docs, metadatas, distances)
        ]

    def hybrid_search(
        self,
        query_text: str,
        query_embedding: list[float],
        k: int,
        version_ids: list[str],
        **kwargs: dict[str, Any]
    ) -> list[RetrieveDocument]:
        """
        Hybrid search - Not supported by ChromaDB

        ChromaDB does not natively support full-text/BM25 search.
        Use LanceDB for hybrid search capabilities.
        """
        raise NotImplementedError(
            "ChromaDB does not support hybrid search. "
            "Please use LanceDB for hybrid search capabilities, "
            "or use only similarity_search with ChromaDB."
        )

    def health_check(self) -> bool:
        """
        ChromaDB 헬스체크 (컬렉션 접근 및 연결 확인)

        Returns:
            bool: 헬스체크 통과 시 True

        Raises:
            FileNotFoundError: persist_dir이 존재하지 않는 경우
            RuntimeError: 컬렉션 접근 실패 시
        """
        from pathlib import Path

        # 1. 디렉토리 존재 확인
        persist_path = Path(self.persist_dir)
        if not persist_path.exists():
            raise FileNotFoundError(
                f"ChromaDB directory not found: {persist_path}\n"
                f"Physical VectorDB files are missing.\n"
                f"Please check your VectorDB configuration."
            )

        # 2. 컬렉션 접근 확인
        try:
            _ = self.collection.count()
            return True
        except Exception as e:
            raise RuntimeError(
                f"Failed to access ChromaDB collection '{self.collection.name}': {e}\n"
                f"Collection may be corrupted. Please run 'chatbot remove <group>' and re-ingest."
            )
