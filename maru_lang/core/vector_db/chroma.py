import logging
import chromadb
from typing import Any

logger = logging.getLogger(__name__)
from chromadb.api.models.Collection import Collection
from langchain_core.documents import Document
from maru_lang.constants import CHROMA_MAX_BATCH_SIZE
from maru_lang.core.vector_db.base import VectorDB


class ChromaVectorDB(VectorDB):
    def __init__(
        self,
        collection_name: str,
        persist_dir: str | None = None,
        host: str | None = None,
        port: int | None = None,
        ssl: bool = False,
    ):
        # Two modes:
        #  - Embedded (persist_dir): single-process local files. Fine for one
        #    server doing in-process ingest, NOT for the task queue (the worker's
        #    writes aren't visible to a separate API process, and concurrent
        #    writers can corrupt the store).
        #  - Server (host/port -> HttpClient): one shared store that both the API
        #    and the ARQ worker connect to — required for queue mode.
        if host:
            self.persist_dir = None
            self.client = chromadb.HttpClient(host=host, port=port or 8000, ssl=ssl)
        else:
            self.persist_dir = persist_dir
            self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection: Collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        # 기존 collection이 L2로 생성된 경우 경고
        space = (self.collection.metadata or {}).get("hnsw:space", "l2")
        if space != "cosine":
            logger.warning(
                f"Collection '{collection_name}' uses '{space}' distance (not cosine). "
                f"Scores may be inaccurate. Re-ingest documents to fix: "
                f"drop the collection and re-upload."
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
            logger.error(f"Failed to delete document chunks from VectorDB: {e}")
            return 0

    def upsert_documents(
        self,
        documents: list[dict],
        embeddings: list[list[float]],
    ) -> None:
        """Add or update documents in VectorDB."""

        contents = [doc["content"] for doc in documents]
        ids = [doc["id"] for doc in documents]
        metadatas = [doc["metadata"] for doc in documents]

        total_items = len(documents)
        for i in range(0, total_items, CHROMA_MAX_BATCH_SIZE):
            end_idx = min(i + CHROMA_MAX_BATCH_SIZE, total_items)

            self.collection.upsert(
                documents=contents[i:end_idx],
                embeddings=embeddings[i:end_idx],
                ids=ids[i:end_idx],
                metadatas=metadatas[i:end_idx]
            )

    def get_chunk_ids_by_document_id(self, document_id: str) -> list[str]:
        """Get all chunk IDs for a document."""
        try:
            results = self.collection.get(
                where={"document_id": {"$eq": document_id}},
                include=[]
            )
            return results["ids"]
        except Exception:
            return []

    def delete_chunks_by_ids(self, chunk_ids: list[str]) -> int:
        """Delete chunks by their IDs."""
        if not chunk_ids:
            return 0
        try:
            self.collection.delete(ids=chunk_ids)
            return len(chunk_ids)
        except Exception:
            return 0

    def count_documents(self) -> int:
        return len(self.collection.get()["ids"])  # 예시: ChromaDB의 문서 ID 개수

    def get_all_metadata(self) -> list[dict]:
        """
        전체 메타데이터 가져오기
        """
        return self.collection.get(include=["metadatas"])["metadatas"]

    def get_documents(self, document_ids: list[str]) -> list[Document]:
        results = self.collection.get(
            where={"document_id": {"$in": document_ids}})

        docs = results["documents"]
        ids = results["ids"]
        metadatas = results["metadatas"]

        return [
            Document(
                id=doc_id,
                page_content=doc,
                metadata=metadata
            )
            for doc_id, doc, metadata in zip(ids, docs, metadatas)
        ]

    def get_all_documents(
        self,
        team_ids: list[int]
    ) -> list[Document]:
        """
        Get all documents from VectorDB filtered by team IDs

        Args:
            team_ids: List of Team IDs to filter

        Returns:
            List of documents filtered by teams
        """
        if not team_ids:
            return []

        filter_where = {"team_id": {"$in": team_ids}}

        results = self.collection.get(
            where=filter_where,
            include=["documents", "metadatas"]
        )

        docs = results["documents"] or []
        ids = results["ids"] or []
        metadatas = results["metadatas"] or []

        return [
            Document(
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
        team_ids: list[int],
        **kwargs: dict[str, Any],
    ) -> list[Document]:
        """
        Vector similarity search

        Args:
            query_embedding: Query embedding vector
            k: Number of results to return
            team_ids: List of Team IDs to filter
        """
        if not team_ids:
            return []

        exclude_ids = set(kwargs.get("exclude_ids", []))
        filter_where = {"team_id": {"$in": team_ids}}
        fetch_k = k + len(exclude_ids) if exclude_ids else k

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=fetch_k,
            where=filter_where
        )

        docs = results["documents"][0] if results["documents"] else []
        ids = results["ids"][0] if results["ids"] else []
        metadatas = results["metadatas"][0] if results["metadatas"] else []
        distances = results["distances"][0] if results["distances"] else []

        return [
            Document(
                id=doc_id,
                page_content=doc,
                metadata={**metadata, "score": 1 - distance}
            )
            for doc_id, doc, metadata, distance in zip(ids, docs, metadatas, distances)
            if doc_id not in exclude_ids
        ][:k]

    def hybrid_search(
        self,
        query_text: str,
        query_embedding: list[float],
        k: int,
        team_ids: list[int],
        **kwargs: dict[str, Any]
    ) -> list[Document]:
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

        # 1. 디렉토리 존재 확인 (embedded 모드에만 해당; HTTP 모드는 서버가 소유)
        if self.persist_dir is not None:
            persist_path = Path(self.persist_dir)
            if not persist_path.exists():
                raise FileNotFoundError(
                    f"ChromaDB directory not found: {persist_path}\n"
                    f"Physical VectorDB files are missing.\n"
                    f"Please check your VectorDB configuration."
                )

        # 2. 컬렉션 접근 확인 (HTTP 모드면 서버 연결까지 검증)
        try:
            _ = self.collection.count()
            return True
        except Exception as e:
            raise RuntimeError(
                f"Failed to access ChromaDB collection '{self.collection.name}': {e}\n"
                f"Collection may be corrupted. Please run 'chatbot remove <group>' and re-ingest."
            )
