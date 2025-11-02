"""
Retriever: 검색 로직 관리 (VectorDB + Embedder + Reranker 조합)
"""
import logging
import numpy as np
from typing import List, Optional, Literal, Tuple, Dict
from maru_lang.pluggable.embedders import Embedder, get_embedder
from konlpy.tag import Okt
from rank_bm25 import BM25Okapi
from maru_lang.core.vector_db.base import VectorDB, RetrieveDocument
from maru_lang.configs import get_config_manager
from maru_lang.pluggable.rerankers import get_reranker, Reranker
from maru_lang.pluggable.models.reranker import RerankerConfig
from maru_lang.pluggable.models.rag import RagConfig
from maru_lang.services.document import get_all_descendant_group_names
from maru_lang.pluggable.agents.agent_factory import AgentFactory
from maru_lang.configs import get_config_manager
from maru_lang.core.relation_db.models.documents import DocumentGroup


logger = logging.getLogger(__name__)

RetriveMethod = Literal["vector", "ensemble"]

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
        rag_config: Optional[RagConfig] = None,
    ):
        """
        Args:
            vdb: VectorDB 인스턴스
            reranker: Reranker 인스턴스 (method="model"일 때만 필요)
            reranker_config: Reranker 설정
        """
        config_manager = get_config_manager()

        self.vdb = vdb
        self.embedder = embedder or get_embedder()
        self.reranker = reranker or get_reranker()
        self.rag_config = rag_config or config_manager.get_rag_config()
        self.reranker_config = reranker_config or config_manager.get_reranker_config()
        self._representative_vectors = None
        self.okt: Optional[Okt] = None  # BM25용 형태소 분석기

    async def search(
        self,
        query: str,
        top_k: int,
        embedding_model: str,
        keywords: Optional[List[str]] = None,
        document_groups: Optional[List[str]] = None,
        retrive_method: Optional[RetriveMethod] = None,
        **kwargs,
    ) -> List[RetrieveDocument]:

        results: List[RetrieveDocument] = []

        # 방어: document_groups가 없으면 검색하지 않음 (보안)
        if not document_groups:
            print("⚠️ No document_groups provided - refusing to search all documents")
            return []

        print(f"document_groups: {document_groups}")
        # 1. 그룹 이름으로부터 version_ids 추출
        all_group_names = await get_all_descendant_group_names(document_groups)
        print(f"all_group_names: {all_group_names}")
        if not all_group_names:
            print("⚠️ No valid groups found after expansion")
            return []

        # 2. 그룹 이름으로 DocumentGroup 조회하여 version_ids 추출
        version_ids = []
        if all_group_names:
            groups = await DocumentGroup.filter(name__in=all_group_names).all()
            version_ids = [group.version_id for group in groups if group.version_id]

        # 방어: version_ids가 없으면 검색하지 않음
        if not version_ids:
            print("⚠️ No valid version_ids found - refusing to search")
            return []
        # 검색 수행
        if retrive_method == "vector":
            results = self._vector_search(
                query, top_k, embedding_model, version_ids, **kwargs)
        elif retrive_method == "ensemble":
            results = self._ensemble_search(
                query, top_k, keywords, embedding_model, version_ids, **kwargs)
        else:
            raise ValueError(f"Unknown search method: {retrive_method}")

        return results

    def _vector_search(
        self,
        query: str,
        k: int,
        embedding_model: str,
        version_ids: Optional[List[str]],
        **kwargs,
    ) -> List[RetrieveDocument]:
        """Vector similarity search"""
        query_embedding = self.embedder.encode([query], embedding_model)[0]
        # VectorDB 검색
        return self.vdb.similarity_search(
            query_embedding=query_embedding,
            k=k,
            version_ids=version_ids,
            **kwargs,
        )

    def _bm25_search(
        self,
        query: str,
        k: int,
        version_ids: Optional[List[str]],
        **kwargs,
    ) -> List[RetrieveDocument]:
        """
        BM25 search implementation

        Args:
            query: Search query
            k: Number of results to return
            version_ids: Optional list of version IDs to filter
            **kwargs: Additional parameters (target_field, etc.)
        """
        if not self.okt:
            self.okt = Okt()

        target_field = kwargs.get("target_field", "document_name")

        # Get all documents from VectorDB with version filter
        all_allowed_chunks = self.vdb.get_all_documents(version_ids=version_ids)

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
        keywords: List[str],
        embedding_model: str,
        version_ids: Optional[List[str]],
        **kwargs,
    ) -> List[RetrieveDocument]:
        """Ensemble search (vector + BM25 with RRF fusion)"""

        # BM25 검색
        bm25_k = kwargs.pop("bm25_k", k)
        # keywords가 리스트면 문자열로 join
        bm25_query = ' '.join(keywords) if isinstance(keywords, list) else keywords
        bm25_docs = self._bm25_search(
            query=bm25_query,
            k=bm25_k,
            version_ids=version_ids,
        )

        query_embedding = self.embedder.encode([query], embedding_model)[0]

        # Vector similarity 검색
        cosine_k = kwargs.pop("cosine_k", k)
        cosine_docs = self.vdb.similarity_search(
            query_embedding=query_embedding,
            k=cosine_k,
            version_ids=version_ids,
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

    def should_rerank(self) -> bool:
        """Check if reranking should be performed"""
        return self.reranker_config is not None and self.reranker_config.enabled

    async def rerank_results(
        self,
        query: str,
        all_results: Dict[str, List[RetrieveDocument]],
    ) -> Dict[str, List[RetrieveDocument]]:
        """
        Rerank search results using model or agent

        모든 그룹의 결과를 합쳐서 reranking 후 다시 그룹별로 분배

        Args:
            query: 검색 쿼리
            all_results: 그룹별 검색 결과 {group_name: [documents]}

        Returns:
            그룹별 reranked 결과 {group_name: [reranked_documents]}
        """
        if not all_results:
            return all_results

        # 1. 모든 그룹의 결과를 하나로 합치기 (그룹 정보 보존)
        all_docs = []
        doc_to_group = {}  # document index -> group name 매핑

        for group_name, docs in all_results.items():
            for doc in docs:
                doc_idx = len(all_docs)
                all_docs.append(doc)
                doc_to_group[doc_idx] = group_name

        if not all_docs:
            return all_results

        # 2. 전체 문서에 대해 reranking 수행
        # Config에서 reranking 방식 확인
        method = self.reranker_config.method if self.reranker_config else "model"
        top_k = self.reranker_config.top_k if self.reranker_config else None

        if method == "agent":
            reranked_docs = await self._rerank_with_agent(query, all_docs, top_k)
        elif method == "model":
            reranked_docs = self._rerank_with_model(query, all_docs, top_k)
        else:
            reranked_docs = all_docs

        # 3. Reranked 결과를 다시 그룹별로 분배
        reranked_by_group = {group: [] for group in all_results.keys()}

        # 효율성을 위해 doc.id -> original_idx 매핑 생성 (O(n) 대신 O(1) 조회)
        doc_id_to_idx = {doc.id: idx for idx, doc in enumerate(all_docs)}

        for doc in reranked_docs:
            # 원본 문서의 인덱스 찾기
            original_idx = doc_id_to_idx.get(doc.id)

            if original_idx is not None and original_idx in doc_to_group:
                group_name = doc_to_group[original_idx]
                reranked_by_group[group_name].append(doc)

        return reranked_by_group

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

    async def _rerank_with_agent(
        self,
        query: str,
        results: List[RetrieveDocument],
        top_k: int,
    ) -> List[RetrieveDocument]:
        """Agent 기반 reranking (LLM 등)"""

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

            # Sync context에서 async agent 실행
            agent_result = await agent.execute(
                query=query,
                documents=results,
                top_k=top_k,
            )

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
                        [query_text], embedding_model
                    )[0]
                    self._representative_vectors[query_type] = embedding
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
        >>> from maru_lang.pluggable.retrievers import get_retriever
        >>>
        >>> # system_config.yaml의 vector_db.type에 따라 자동으로 VectorDB 생성
        >>> vdb = get_vector_db()
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

        _retriever_instance = Retriever(
            vdb=vdb,
        )

    return _retriever_instance
