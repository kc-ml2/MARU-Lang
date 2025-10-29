import chromadb
import asyncio
from typing import Any
from chromadb.api.models.Collection import Collection
from konlpy.tag import Okt
from rank_bm25 import BM25Okapi
from maru_lang.core.vector_db.base import VectorDB
from maru_lang.core.vector_db.retrieve_document import RetrieveDocument
from maru_lang.core.settings import settings


class ChromaVectorDB(VectorDB):
    def __init__(
        self,
        persist_dir: str,
        collection_name: str,
    ):
        self.okt: Okt | None = None
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
        store_text: bool = True
    ) -> None:
        """
        문서를 VectorDB에 추가

        Args:
            documents: 문서 리스트 (id, content, metadata 포함)
            embeddings: 임베딩 벡터 리스트 (외부에서 생성)
            store_text: 텍스트 저장 여부
        """
        contents = [doc["content"] for doc in documents]

        # store_text 파라미터에 따라 텍스트 저장 여부 결정
        docs_to_store = contents if store_text else []

        self.collection.add(
            documents=docs_to_store,
            embeddings=embeddings,
            ids=[doc["id"] for doc in documents],
            metadatas=[doc["metadata"] for doc in documents]
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
        store_text: bool = True
    ) -> None:
        """
        문서 업데이트

        Args:
            doc_id: 기존 문서 ID
            new_doc_id: 새 문서 ID
            new_content: 새 문서 내용
            embedding: 새 임베딩 벡터 (외부에서 생성)
            store_text: 텍스트 저장 여부
        """
        try:
            existing = self.collection.get(ids=[doc_id])
            if not existing["ids"]:
                raise ValueError(f"Document with id={doc_id} not found")

            old_metadata = existing["metadatas"][0]

            # store_text 파라미터에 따라 텍스트 저장 여부 결정
            docs_to_store = [new_content] if store_text else []

            # 먼저 삭제
            self.collection.delete(ids=[doc_id])
            # 다시 추가
            self.collection.add(
                documents=docs_to_store,
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

    def similarity_search(
        self,
        query_embedding: list[float],
        k: int,
        document_groups: list[str] | None = None,
        **kwargs: dict[str, Any],
    ) -> list[RetrieveDocument]:
        """
        유사도 검색 (그룹 기반)

        Args:
            query_embedding: 쿼리 임베딩 벡터 (외부에서 생성)
            k: 반환할 결과 개수
            document_groups: 그룹 이름 필터 (None이면 전체 검색)
        """
        # 그룹 필터 생성
        if document_groups:
            filter = {"group": {"$in": document_groups}}
        else:
            filter = None  # 전체 검색

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

    def bm25_search(
        self,
        query: str,
        k: int,
        document_groups: list[str] | None = None,
        target_field: str | None = "document_name",
    ) -> list[RetrieveDocument]:
        """
        BM25 검색 (그룹 기반)

        Args:
            query: 검색 쿼리
            k: 반환할 결과 개수
            document_groups: 그룹 이름 필터 (None이면 전체 검색)
            target_field: BM25 대상 필드
        """
        if not self.okt:
            self.okt = Okt()

        # 그룹 필터로 문서 가져오기
        if document_groups:
            filter = {"group": {"$in": document_groups}}
        else:
            filter = None

        result = self.collection.get(
            where=filter,
            include=["documents", "metadatas"]
        )

        all_allowed_chunks = [
            RetrieveDocument(
                id=doc_id,
                page_content=doc,
                metadata=metadata
            )
            for doc_id, doc, metadata in zip(result["ids"], result["documents"], result["metadatas"])
        ]
        if not all_allowed_chunks:
            return []

        unique_docs = {}
        for chunk in all_allowed_chunks:
            title = chunk.metadata.get(target_field, "")
            if title and title not in unique_docs:
                unique_docs[title] = chunk

        representative_chunks = list(unique_docs.values())
        if not representative_chunks:
            return []

        if target_field:
            tokenized_docs = [self.okt.morphs(
                doc.metadata[target_field]) for doc in representative_chunks]

        bm25 = BM25Okapi(tokenized_docs)

        scores = bm25.get_scores(self.okt.morphs(query))
        doc_scores = [(score, idx, representative_chunks[idx])
                      for idx, score in enumerate(scores)]
        doc_scores.sort(key=lambda x: x[0], reverse=True)

        return [
            RetrieveDocument(
                id=doc.id,
                page_content=doc.page_content,
                metadata={**doc.metadata, "bm25_score": score}
            )
            for score, idx, doc in doc_scores[:k]
        ]

    def ensemble_search(
        self,
        query_embedding: list[float],
        k: int,
        cosine_k: int,
        document_groups: list[str] | None = None,
        bm25_docs: list[RetrieveDocument] = [],
        cosine_weight: float = 0.7,
        bm25_weight: float = 0.3,
    ) -> list[RetrieveDocument]:
        """
        Ensemble 검색 (그룹 기반)

        Args:
            query_embedding: 쿼리 임베딩 벡터 (외부에서 생성)
            k: 반환할 결과 개수
            cosine_k: Cosine 검색 결과 개수
            document_groups: 그룹 이름 필터 (None이면 전체 검색)
            bm25_docs: BM25 검색 결과 (optional)
            cosine_weight: Cosine 가중치
            bm25_weight: BM25 가중치
        """
        cosine_docs = self.similarity_search(
            query_embedding=query_embedding,
            k=cosine_k,
            document_groups=document_groups,
        )

        return self._apply_rrf_fusion(cosine_docs, bm25_docs, cosine_weight, bm25_weight, k)

    def _apply_rrf_fusion(
        self,
        cosine_docs: list[RetrieveDocument],
        bm25_docs: list[RetrieveDocument],
        cosine_weight: float,
        bm25_weight: float,
        k: int
    ) -> list[RetrieveDocument]:
        """RRF (Reciprocal Rank Fusion) 적용"""
        for i, doc in enumerate(cosine_docs):
            doc.metadata['cos_rank'] = i + 1

        for i, doc in enumerate(bm25_docs):
            doc.metadata['bm25_rank'] = i + 1

        doc_dict: dict[str, RetrieveDocument] = {}
        for doc in cosine_docs:
            doc_id = doc.metadata.get('id')
            doc_dict[doc_id] = doc

        for doc in bm25_docs:
            doc_id = doc.metadata.get('id')
            if doc_id in doc_dict:
                doc_dict[doc_id].metadata['bm25_rank'] = doc.metadata['bm25_rank']
            else:
                doc_dict[doc_id] = doc
                doc.metadata['cos_rank'] = 9999

        for doc in doc_dict.values():
            bm_rnk = doc.metadata.get('bm25_rank', 9999)
            cos_rnk = doc.metadata.get('cos_rank', 9999)
            rrf_score = (bm25_weight / (k + bm_rnk)) + \
                (cosine_weight / (k + cos_rnk))
            doc.metadata['rrf_score'] = rrf_score

        sorted_docs = sorted(doc_dict.values(), key=lambda x: x.metadata.get(
            'rrf_score', 0), reverse=True)
        return sorted_docs[:k]

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
