"""
Retriever: 검색 로직 관리 (VectorDB + Embedder + Reranker 조합)
"""
from typing import List, Optional, Literal, Tuple
import logging
import numpy as np
from konlpy.tag import Okt
from rank_bm25 import BM25Okapi
from maru_lang.core.vector_db.base import VectorDB, RetrieveDocument
from maru_lang.pluggable.embedders import get_embedder, Embedder
from maru_lang.pluggable.rerankers import get_reranker, Reranker
from maru_lang.pluggable.models.reranker import RerankerConfig

logger = logging.getLogger(__name__)

SearchMethod = Literal["vector", "bm25", "ensemble"]

# 기본값 상수 정의
DEFAULT_QUERY_TYPE_WEIGHTS = {
    "factual": (0.2, 0.8),
    "procedural": (0.8, 0.2),
    "analytical": (0.5, 0.5),
}

DEFAULT_REPRESENTATIVE_QUERIES = {
    "factual": "~은 무엇인가",
    "procedural": "~하는 방법",
    "analytical": "A와 B비교 분석",
}

DEFAULT_SIMILARITY_THRESHOLD = 0.3

DEFAULT_FALLBACK_CONFIG = {
    'short_query_length': 2,
    'long_query_length': 6,
    'short_query_weights': (0.3, 0.7),
    'medium_query_weights': (0.5, 0.5),
    'long_query_weights': (0.7, 0.3),
}


class Retriever:
    """
    검색 관리자

    VectorDB, Embedder, Reranker를 조합하여 다양한 검색 방법 제공
    """

    def __init__(
        self,
        vdb: VectorDB,
        embedder: Optional[Embedder] = None,
        reranker: Optional[Reranker] = None,
        reranker_config: Optional[RerankerConfig] = None,
    ):
        """
        Args:
            vdb: VectorDB 인스턴스
            embedder: Embedder 인스턴스 (None이면 자동 생성)
            reranker: Reranker 인스턴스 (None이면 자동 생성)
            reranker_config: Reranker 설정
        """
        self.vdb = vdb
        self.embedder = embedder or get_embedder()
        self.reranker = reranker or get_reranker()
        self.reranker_config = reranker_config
        self._representative_vectors = None
        self.okt: Optional[Okt] = None  # BM25용 형태소 분석기

    def search(
        self,
        query: str,
        k: int,
        method: SearchMethod = "vector",
        document_groups: Optional[List[str]] = None,
        use_reranking: Optional[bool] = None,
        embedding_model: Optional[str] = None,
        **kwargs,
    ) -> List[RetrieveDocument]:
        """
        통합 검색 메서드

        Args:
            query: 검색 쿼리
            k: 반환할 결과 개수
            method: 검색 방법 ("vector", "bm25", "ensemble") - 기본값: ensemble
            document_groups: 그룹 이름 필터
            use_reranking: reranking 사용 여부 (None이면 config 따름)
            embedding_model: 임베딩 모델 이름 (None이면 config에서 자동 로드)
            **kwargs: 메서드별 추가 파라미터

        Returns:
            검색 결과 리스트
        """
        # Embedding model 자동 로드 (vector/ensemble 시 필요)
        if method in ("vector", "ensemble") and embedding_model is None:
            embedding_model = self._get_default_embedding_model()

        # 검색 수행
        if method == "vector":
            results = self._vector_search(
                query, k, document_groups, embedding_model, **kwargs
            )
        elif method == "bm25":
            results = self._bm25_search(query, k, document_groups, **kwargs)
        elif method == "ensemble":
            results = self._ensemble_search(
                query, k, document_groups, embedding_model, **kwargs
            )
        else:
            raise ValueError(f"Unknown search method: {method}")

        # Reranking 적용 (옵션)
        should_rerank = self._should_use_reranking(use_reranking)
        if should_rerank and results:
            results = self._rerank_results(query, results, k)

        return results

    def _get_default_embedding_model(self) -> str:
        """Config에서 기본 임베딩 모델 로드"""
        try:
            from maru_lang.configs import get_config_manager

            config_manager = get_config_manager()
            embedder_config = config_manager.get_embedder_config()

            if embedder_config and embedder_config.default_model:
                return embedder_config.default_model
        except Exception:
            pass

        # 폴백 기본값
        return "BAAI/bge-m3"

    def _vector_search(
        self,
        query: str,
        k: int,
        document_groups: Optional[List[str]],
        embedding_model: Optional[str],
        **kwargs,
    ) -> List[RetrieveDocument]:
        """Vector similarity search"""
        if not embedding_model:
            raise ValueError("embedding_model is required for vector search")

        # 쿼리 임베딩
        query_embedding = self.embedder.encode(
            [query], embedding_model, show_progress=False
        )[0]

        # VectorDB 검색
        return self.vdb.similarity_search(
            query_embedding=query_embedding,
            k=k,
            document_groups=document_groups,
            **kwargs,
        )

    def _bm25_search(
        self,
        query: str,
        k: int,
        document_groups: Optional[List[str]],
        **kwargs,
    ) -> List[RetrieveDocument]:
        """
        BM25 search implementation

        Args:
            query: Search query
            k: Number of results to return
            document_groups: Optional list of document groups to filter
            **kwargs: Additional parameters (target_field, etc.)
        """
        if not self.okt:
            self.okt = Okt()

        target_field = kwargs.get("target_field", "document_name")

        # Get all documents from VectorDB with group filter
        all_allowed_chunks = self.vdb.get_all_documents(document_groups=document_groups)

        if not all_allowed_chunks:
            return []

        # Get unique documents by target field
        unique_docs = {}
        for chunk in all_allowed_chunks:
            title = chunk.metadata.get(target_field, "")
            if title and title not in unique_docs:
                unique_docs[title] = chunk

        representative_chunks = list(unique_docs.values())
        if not representative_chunks:
            return []

        # Tokenize documents
        if target_field:
            tokenized_docs = [
                self.okt.morphs(doc.metadata[target_field])
                for doc in representative_chunks
            ]

        # Build BM25 index
        bm25 = BM25Okapi(tokenized_docs)

        # Calculate scores
        scores = bm25.get_scores(self.okt.morphs(query))
        doc_scores = [
            (score, idx, representative_chunks[idx])
            for idx, score in enumerate(scores)
        ]
        doc_scores.sort(key=lambda x: x[0], reverse=True)

        # Return top-k results with scores
        return [
            RetrieveDocument(
                id=doc.id,
                page_content=doc.page_content,
                metadata={**doc.metadata, "bm25_score": score}
            )
            for score, idx, doc in doc_scores[:k]
        ]

    def _ensemble_search(
        self,
        query: str,
        k: int,
        document_groups: Optional[List[str]],
        embedding_model: Optional[str],
        **kwargs,
    ) -> List[RetrieveDocument]:
        """Ensemble search (vector + BM25 with RRF fusion)"""
        if not embedding_model:
            raise ValueError("embedding_model is required for ensemble search")

        # 쿼리 임베딩
        query_embedding = self.embedder.encode(
            [query], embedding_model, show_progress=False
        )[0]

        # BM25 검색
        bm25_k = kwargs.pop("bm25_k", k)
        bm25_docs = self._bm25_search(
            query=query,
            k=bm25_k,
            document_groups=document_groups,
        )

        # Vector similarity 검색
        cosine_k = kwargs.pop("cosine_k", k)
        cosine_docs = self.vdb.similarity_search(
            query_embedding=query_embedding,
            k=cosine_k,
            document_groups=document_groups,
        )

        # Semantic weight 자동 계산 (명시적으로 제공되지 않은 경우)
        cosine_weight = kwargs.pop("cosine_weight", None)
        bm25_weight = kwargs.pop("bm25_weight", None)

        if cosine_weight is None or bm25_weight is None:
            # 쿼리 특성 분석하여 가중치 자동 결정
            cosine_weight, bm25_weight = self._get_semantic_weights(
                query, query_embedding, embedding_model
            )

        # RRF Fusion 적용
        return self._apply_rrf_fusion(
            cosine_docs=cosine_docs,
            bm25_docs=bm25_docs,
            cosine_weight=cosine_weight,
            bm25_weight=bm25_weight,
            k=k
        )

    def _apply_rrf_fusion(
        self,
        cosine_docs: List[RetrieveDocument],
        bm25_docs: List[RetrieveDocument],
        cosine_weight: float,
        bm25_weight: float,
        k: int
    ) -> List[RetrieveDocument]:
        """
        Apply RRF (Reciprocal Rank Fusion) to combine vector and BM25 search results

        Args:
            cosine_docs: Vector similarity search results
            bm25_docs: BM25 search results
            cosine_weight: Weight for cosine similarity scores
            bm25_weight: Weight for BM25 scores
            k: Number of final results to return

        Returns:
            Fused and ranked list of documents
        """
        # Assign ranks to documents
        for i, doc in enumerate(cosine_docs):
            doc.metadata['cos_rank'] = i + 1

        for i, doc in enumerate(bm25_docs):
            doc.metadata['bm25_rank'] = i + 1

        # Merge documents by ID
        doc_dict: dict[str, RetrieveDocument] = {}

        for doc in cosine_docs:
            doc_id = doc.metadata.get('id')
            doc_dict[doc_id] = doc

        for doc in bm25_docs:
            doc_id = doc.metadata.get('id')
            if doc_id in doc_dict:
                # Document appears in both results, add BM25 rank
                doc_dict[doc_id].metadata['bm25_rank'] = doc.metadata['bm25_rank']
            else:
                # Document only in BM25 results
                doc_dict[doc_id] = doc
                doc.metadata['cos_rank'] = 9999  # Large rank for missing documents

        # Calculate RRF scores
        for doc in doc_dict.values():
            bm_rnk = doc.metadata.get('bm25_rank', 9999)
            cos_rnk = doc.metadata.get('cos_rank', 9999)
            rrf_score = (bm25_weight / (k + bm_rnk)) + (cosine_weight / (k + cos_rnk))
            doc.metadata['rrf_score'] = rrf_score

        # Sort by RRF score and return top-k
        sorted_docs = sorted(
            doc_dict.values(),
            key=lambda x: x.metadata.get('rrf_score', 0),
            reverse=True
        )
        return sorted_docs[:k]

    def _should_use_reranking(self, use_reranking: Optional[bool]) -> bool:
        """Reranking 사용 여부 결정"""
        # 명시적으로 지정된 경우 그대로 사용
        if use_reranking is not None:
            return use_reranking

        # Config에서 확인
        if self.reranker_config:
            return self.reranker_config.enabled

        # 기본값: False
        return False

    def _rerank_results(
        self,
        query: str,
        results: List[RetrieveDocument],
        top_k: int,
    ) -> List[RetrieveDocument]:
        """Rerank search results using model or agent"""
        if not results:
            return results

        # Config에서 reranking 방식 확인
        method = self.reranker_config.method if self.reranker_config else "model"

        if method == "agent":
            return self._rerank_with_agent(query, results, top_k)
        else:
            return self._rerank_with_model(query, results, top_k)

    def _rerank_with_model(
        self,
        query: str,
        results: List[RetrieveDocument],
        top_k: int,
    ) -> List[RetrieveDocument]:
        """Model 기반 reranking"""
        # Config 확인
        if not self.reranker_config or not self.reranker_config.default_model:
            logger.error(
                "Reranking is enabled but reranker_config or default_model is not configured. "
                "Skipping reranking. Please configure reranker_config.yaml with a default_model."
            )
            return results

        # 문서 내용 추출
        documents = [doc.page_content for doc in results]

        try:
            # Reranking
            ranked = self.reranker.rerank(
                query=query,
                documents=documents,
                model_name=self.reranker_config.default_model,
                top_k=top_k,
            )

            # 재정렬된 순서로 결과 반환
            reranked_results = []
            for idx, score in ranked:
                doc = results[idx]
                # reranker score를 metadata에 추가
                doc.metadata["reranker_score"] = score
                reranked_results.append(doc)

            return reranked_results
        except Exception as e:
            logger.error(f"Model-based reranking failed: {e}. Returning original results.")
            return results

    def _rerank_with_agent(
        self,
        query: str,
        results: List[RetrieveDocument],
        top_k: int,
    ) -> List[RetrieveDocument]:
        """Agent 기반 reranking (LLM 등)"""
        import asyncio
        from maru_lang.pluggable.agents.agent_factory import AgentFactory
        from maru_lang.configs import get_config_manager

        try:
            # Agent 이름 확인
            agent_name = self.reranker_config.agent_name if self.reranker_config else None
            if not agent_name:
                logger.error(
                    "Reranking method is 'agent' but agent_name is not configured. "
                    "Skipping reranking. Please configure reranker_config.yaml with agent_name."
                )
                return results

            # Agent 로드
            config_manager = get_config_manager()
            agent_config = config_manager.get_agent(agent_name)
            if not agent_config:
                logger.error(
                    f"Reranker agent '{agent_name}' not found in agent_config.yaml. "
                    f"Skipping reranking. Please register the agent in agent_config.yaml."
                )
                return results

            # Agent 생성 및 실행
            factory = AgentFactory()
            agent = factory.create_agent(agent_name, agent_config)
            if not agent:
                logger.error(
                    f"Failed to create reranker agent '{agent_name}'. "
                    f"Skipping reranking. Check agent implementation and configuration."
                )
                return results

            # Agent 초기화 및 실행 (async)
            async def run_agent():
                await agent.initialize()
                result = await agent.execute(
                    query=query,
                    documents=results,
                    top_k=top_k,
                )
                return result

            # Sync context에서 async agent 실행
            agent_result = asyncio.run(run_agent())

            # Agent 결과 처리
            if agent_result.success and agent_result.data:
                # data는 reranked document indices와 scores 리스트
                # 형식: [(idx, score), (idx, score), ...]
                reranked_results = []
                for idx, score in agent_result.data[:top_k]:
                    if 0 <= idx < len(results):
                        doc = results[idx]
                        doc.metadata["reranker_score"] = score
                        reranked_results.append(doc)
                return reranked_results
            else:
                logger.error(
                    f"Reranker agent '{agent_name}' execution failed: {agent_result.error}. "
                    f"Skipping reranking. Returning original results."
                )
                return results

        except Exception as e:
            logger.error(
                f"Error during agent-based reranking: {e}. "
                f"Skipping reranking. Returning original results."
            )
            return results

    def _get_semantic_weights(
        self,
        query: str,
        query_embedding: List[float],
        embedding_model: str,
    ) -> Tuple[float, float]:
        """
        쿼리의 의미적 특성을 embedding으로 분석하여 가중치를 결정

        Args:
            query: 사용자 쿼리
            query_embedding: 쿼리 임베딩 벡터 (이미 계산된 경우)
            embedding_model: 임베딩 모델 이름

        Returns:
            tuple[float, float]: (cosine_weight, bm25_weight)
        """
        try:
            # 대표 벡터들 가져오기
            representative_vectors = self._get_representative_vectors(embedding_model)
            if representative_vectors is None:
                # 임베딩 실패 시 기본 로직으로 폴백
                return self._fallback_weight_logic(query)

            # Config에서 쿼리 타입별 가중치 로드
            query_type_weights = self._get_query_type_weights_from_config()

            # 각 대표 벡터와의 유사도 계산
            similarities = {}
            for query_type, type_vec in representative_vectors.items():
                similarity = self._cosine_similarity(query_embedding, type_vec)
                similarities[query_type] = similarity

            # 가장 높은 유사도를 보인 타입 선택
            best_match_type = max(similarities, key=similarities.get)
            best_similarity = similarities[best_match_type]

            # Config에서 similarity threshold 가져오기
            similarity_threshold = self._get_similarity_threshold_from_config()

            # 유사도가 너무 낮으면 fallback 로직 사용
            if best_similarity < similarity_threshold:
                return self._fallback_weight_logic(query)

            return query_type_weights[best_match_type]

        except Exception:
            return self._fallback_weight_logic(query)

    def _get_representative_vectors(
        self, 
        embedding_model: str
    ) -> Optional[dict]:
        """대표 쿼리 타입 벡터들을 초기화하거나 캐시된 값을 반환"""

        if self._representative_vectors is None:
            try:
                # Config에서 대표 쿼리 로드
                representative_queries = self._get_representative_queries_from_config()

                self._representative_vectors = {}
                for query_type, query_text in representative_queries.items():
                    embedding = self.embedder.encode(
                        [query_text], embedding_model, show_progress=False
                    )[0]
                    self._representative_vectors[query_type] = embedding

                print("✅ Representative query vectors initialized")
            except Exception as e:
                print(f"⚠️ Failed to initialize representative vectors: {e}")
                return None

        return self._representative_vectors

    @staticmethod
    def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """두 벡터 간의 코사인 유사도 계산"""
        try:
            vec_a = np.array(vec_a)
            vec_b = np.array(vec_b)
            return float(
                np.dot(vec_a, vec_b) / (np.linalg.norm(vec_a) * np.linalg.norm(vec_b))
            )
        except Exception:
            return 0.0

    def _fallback_weight_logic(self, query: str) -> Tuple[float, float]:
        """임베딩 기반 분석 실패 시 사용하는 폴백 로직"""
        words = query.split()

        # Config에서 fallback logic 설정 로드
        fallback_config = self._get_fallback_config()

        # 단어 수 기반 로직
        if len(words) <= fallback_config['short_query_length']:
            return fallback_config['short_query_weights']
        elif len(words) >= fallback_config['long_query_length']:
            return fallback_config['long_query_weights']
        else:
            return fallback_config['medium_query_weights']

    def _get_query_type_weights_from_config(self) -> dict:
        """Config에서 쿼리 타입별 가중치 로드"""
        try:
            from maru_lang.configs import get_config_manager

            config_manager = get_config_manager()
            rag_config = config_manager.get_rag_config()

            if rag_config and rag_config.retriever.query_type_weights:
                # Convert QueryTypeWeights to tuples
                logger.debug("Loaded query type weights from RAG config")
                return {
                    query_type: weights.to_tuple()
                    for query_type, weights in rag_config.retriever.query_type_weights.items()
                }
            else:
                logger.info("RAG config not found or no query_type_weights specified, using default weights")
        except Exception as e:
            logger.warning(f"Failed to load query type weights from config: {e}, using default weights")

        # 기본값
        return DEFAULT_QUERY_TYPE_WEIGHTS

    def _get_representative_queries_from_config(self) -> dict:
        """Config에서 대표 쿼리 로드"""
        try:
            from maru_lang.configs import get_config_manager

            config_manager = get_config_manager()
            rag_config = config_manager.get_rag_config()

            if rag_config and rag_config.retriever.representative_queries:
                logger.debug("Loaded representative queries from RAG config")
                return rag_config.retriever.representative_queries
            else:
                logger.info("RAG config not found or no representative_queries specified, using default queries")
        except Exception as e:
            logger.warning(f"Failed to load representative queries from config: {e}, using default queries")

        # 기본값
        return DEFAULT_REPRESENTATIVE_QUERIES

    def _get_similarity_threshold_from_config(self) -> float:
        """Config에서 similarity threshold 로드"""
        try:
            from maru_lang.configs import get_config_manager

            config_manager = get_config_manager()
            rag_config = config_manager.get_rag_config()

            if rag_config and rag_config.retriever.fallback_logic:
                logger.debug(f"Loaded similarity threshold from RAG config: {rag_config.retriever.fallback_logic.similarity_threshold}")
                return rag_config.retriever.fallback_logic.similarity_threshold
            else:
                logger.info(f"RAG config not found or no fallback_logic specified, using default threshold: {DEFAULT_SIMILARITY_THRESHOLD}")
        except Exception as e:
            logger.warning(f"Failed to load similarity threshold from config: {e}, using default: {DEFAULT_SIMILARITY_THRESHOLD}")

        # 기본값
        return DEFAULT_SIMILARITY_THRESHOLD

    def _get_fallback_config(self) -> dict:
        """Config에서 fallback logic 설정 로드"""
        try:
            from maru_lang.configs import get_config_manager

            config_manager = get_config_manager()
            rag_config = config_manager.get_rag_config()

            if rag_config and rag_config.retriever.fallback_logic:
                fallback = rag_config.retriever.fallback_logic
                logger.debug("Loaded fallback logic from RAG config")
                return {
                    'short_query_length': fallback.short_query_length,
                    'long_query_length': fallback.long_query_length,
                    'short_query_weights': fallback.weights.get('short_query', fallback.weights.get('short_query')).to_tuple() if 'short_query' in fallback.weights else (0.3, 0.7),
                    'medium_query_weights': fallback.weights.get('medium_query', fallback.weights.get('medium_query')).to_tuple() if 'medium_query' in fallback.weights else (0.5, 0.5),
                    'long_query_weights': fallback.weights.get('long_query', fallback.weights.get('long_query')).to_tuple() if 'long_query' in fallback.weights else (0.7, 0.3),
                }
            else:
                logger.info("RAG config not found or no fallback_logic specified, using default fallback config")
        except Exception as e:
            logger.warning(f"Failed to load fallback config: {e}, using default fallback config")

        # 기본값
        return DEFAULT_FALLBACK_CONFIG


# 싱글톤 인스턴스
_retriever_instance: Optional[Retriever] = None


def get_retriever(
    vdb: Optional[VectorDB] = None,
    force_new: bool = False,
) -> Retriever:
    """
    Retriever 싱글톤 인스턴스 반환

    Args:
        vdb: VectorDB 인스턴스 (None이면 새로 생성해야 함)
        force_new: True면 기존 인스턴스 무시하고 새로 생성

    Returns:
        Retriever: 싱글톤 인스턴스

    Example:
        >>> from maru_lang.core.vector_db.factory import get_vector_db
        >>> from maru_lang.models.vector_db import ChromaDBConfig
        >>>
        >>> vdb_config = ChromaDBConfig.from_settings()
        >>> vdb = get_vector_db(vdb_config)
        >>> retriever = get_retriever(vdb)
        >>>
        >>> results = retriever.search(
        ...     query="python tutorial",
        ...     k=5,
        ...     method="vector",
        ...     embedding_model="BAAI/bge-m3",
        ...     use_reranking=True
        ... )
    """
    global _retriever_instance

    if _retriever_instance is None or force_new:
        if vdb is None:
            raise ValueError("vdb is required for first-time Retriever initialization")

        # Config 로드
        from maru_lang.configs import get_config_manager

        config_manager = get_config_manager()
        reranker_config = config_manager.get_reranker_config()

        _retriever_instance = Retriever(
            vdb=vdb,
            reranker_config=reranker_config,
        )

    return _retriever_instance
