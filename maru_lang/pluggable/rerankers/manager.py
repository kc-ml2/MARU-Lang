"""
Reranker: 검색 결과 재정렬
프로세스 단위로 모델을 캐싱하여 GPU 자원을 효율적으로 사용
"""
from typing import Dict, List, Optional, Tuple
from sentence_transformers import CrossEncoder


class Reranker:
    """
    Reranker 관리자

    프로세스 내에서 reranker 모델을 캐싱하여 재사용
    rerank 함수로 검색 결과를 재정렬하는 단순한 인터페이스 제공
    """

    def __init__(self, device: Optional[str] = None):
        """
        Args:
            device: 모델을 로드할 디바이스 (None이면 자동 선택)
                   예: "cuda", "cpu", "mps"
        """
        self.device = device
        self.model_cache: Dict[str, CrossEncoder] = {}

    def rerank(
        self,
        query: str,
        documents: List[str],
        model_name: str,
        top_k: Optional[int] = None,
    ) -> List[Tuple[int, float]]:
        """
        쿼리와 문서들을 재정렬

        Args:
            query: 검색 쿼리
            documents: 재정렬할 문서 리스트
            model_name: reranker 모델 이름
            top_k: 상위 k개만 반환 (None이면 전체)

        Returns:
            List[Tuple[int, float]]: (원본 인덱스, 점수) 튜플 리스트 (점수 내림차순)
        """
        model = self._get_or_load_model(model_name)

        # 쿼리-문서 쌍 생성
        pairs = [[query, doc] for doc in documents]

        # 점수 계산
        scores = model.predict(pairs)

        # (인덱스, 점수) 튜플 생성 및 정렬
        ranked = [(idx, float(score)) for idx, score in enumerate(scores)]
        ranked.sort(key=lambda x: x[1], reverse=True)

        # top_k 제한
        if top_k is not None:
            ranked = ranked[:top_k]

        return ranked

    def _get_or_load_model(self, model_name: str) -> CrossEncoder:
        """
        모델 캐싱 및 로드 (내부 메서드)

        Args:
            model_name: reranker 모델 이름

        Returns:
            CrossEncoder: 로드된 모델 인스턴스
        """
        if model_name not in self.model_cache:
            print(f"Loading reranker model: {model_name}...")
            self.model_cache[model_name] = CrossEncoder(
                model_name, device=self.device
            )
            device_info = f"device={self.device}" if self.device else "auto"
            print(f"✅ Reranker loaded: {model_name} ({device_info})")

        return self.model_cache[model_name]

    def unload_model(self, model_name: str) -> bool:
        """
        모델을 메모리에서 해제

        Args:
            model_name: 해제할 모델 이름

        Returns:
            bool: 해제 성공 여부
        """
        if model_name in self.model_cache:
            del self.model_cache[model_name]
            print(f"🗑️ Reranker unloaded: {model_name}")
            return True
        return False

    def clear_cache(self):
        """모든 캐시된 모델 해제"""
        count = len(self.model_cache)
        self.model_cache.clear()
        print(f"🗑️ Cleared {count} reranker model(s) from cache")


# 싱글톤 인스턴스
_reranker_instance: Optional[Reranker] = None


def get_reranker(
    device: Optional[str] = None,
    force_new: bool = False,
) -> Reranker:
    """
    Reranker 싱글톤 인스턴스 반환

    Args:
        device: 모델을 로드할 디바이스 (None이면 config에서 자동 로드)
               예: "cuda", "cpu", "mps"
        force_new: True면 기존 인스턴스 무시하고 새로 생성 (테스트용)

    Returns:
        Reranker: 싱글톤 인스턴스

    Example:
        >>> reranker = get_reranker()
        >>> ranked = reranker.rerank(
        ...     query="python tutorial",
        ...     documents=["doc1", "doc2", "doc3"],
        ...     model_name="BAAI/bge-reranker-v2-m3",
        ...     top_k=5
        ... )
    """
    global _reranker_instance

    if _reranker_instance is None or force_new:
        # device가 None이면 config에서 로드 (embedder와 동일한 device 사용)
        if device is None:
            device = _load_device_from_config()

        _reranker_instance = Reranker(device=device)

    return _reranker_instance


def _load_device_from_config() -> Optional[str]:
    """
    ConfigManager를 사용하여 config에서 device 설정을 로드합니다.
    Embedder config와 동일한 device 사용

    Returns:
        Optional[str]: config에서 읽은 device 설정, 없으면 None
    """
    try:
        from maru_lang.configs import get_config_manager

        config_manager = get_config_manager()
        embedder_config = config_manager.get_embedder_config()

        if embedder_config:
            return embedder_config.device
    except ImportError:
        pass
    except Exception as e:
        print(f"⚠️ Reranker config 로드 실패: {e}")

    return None
