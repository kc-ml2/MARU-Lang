"""
Embedder: 임베딩 모델 관리 및 벡터 생성
프로세스 단위로 모델을 캐싱하여 GPU 자원을 효율적으로 사용
"""
from typing import Dict, List, Optional
from sentence_transformers import SentenceTransformer


class Embedder:
    """
    임베딩 모델 관리자

    프로세스 내에서 임베딩 모델을 캐싱하여 재사용
    encode 함수로 텍스트를 벡터로 변환하는 단순한 인터페이스 제공
    """

    def __init__(self, device: Optional[str] = None):
        """
        Args:
            device: 모델을 로드할 디바이스 (None이면 자동 선택)
                   예: "cuda", "cpu", "mps"
        """
        self.device = device
        self.model_cache: Dict[str, SentenceTransformer] = {}

    def encode(
        self,
        texts: List[str],
        model_name: str,
        show_progress: bool = True,
    ) -> List[List[float]]:
        """
        텍스트를 임베딩 벡터로 변환

        Args:
            texts: 임베딩할 텍스트 리스트
            model_name: 임베딩 모델 이름
            show_progress: 진행바 표시 여부

        Returns:
            List[List[float]]: 임베딩 벡터 리스트
        """
        model = self._get_or_load_model(model_name)
        vectors = model.encode(
            texts, show_progress_bar=show_progress, convert_to_numpy=True
        )
        return vectors.tolist()

    def get_dimension(self, model_name: str) -> int:
        """
        임베딩 차원 반환

        Args:
            model_name: 임베딩 모델 이름

        Returns:
            int: 임베딩 벡터 차원
        """
        model = self._get_or_load_model(model_name)
        return model.get_sentence_embedding_dimension()

    def _get_or_load_model(self, model_name: str) -> SentenceTransformer:
        """
        모델 캐싱 및 로드 (내부 메서드)

        Args:
            model_name: 임베딩 모델 이름

        Returns:
            SentenceTransformer: 로드된 모델 인스턴스
        """
        if model_name not in self.model_cache:
            print(f"Loading embedding model: {model_name}...")
            self.model_cache[model_name] = SentenceTransformer(
                model_name, device=self.device
            )
            dim = self.model_cache[model_name].get_sentence_embedding_dimension()
            device_info = f"device={self.device}" if self.device else "auto"
            print(f"✅ Model loaded: {model_name} (dim={dim}, {device_info})")

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
            print(f"🗑️ Model unloaded: {model_name}")
            return True
        return False

    def clear_cache(self):
        """모든 캐시된 모델 해제"""
        count = len(self.model_cache)
        self.model_cache.clear()
        print(f"🗑️ Cleared {count} model(s) from cache")


# 싱글톤 인스턴스
_embedder_instance: Optional[Embedder] = None


def get_embedder(
    device: Optional[str] = None,
    force_new: bool = False,
) -> Embedder:
    """
    Embedder 싱글톤 인스턴스 반환

    Args:
        device: 모델을 로드할 디바이스 (None이면 config에서 자동 로드)
               예: "cuda", "cpu", "mps"
        force_new: True면 기존 인스턴스 무시하고 새로 생성 (테스트용)

    Returns:
        Embedder: 싱글톤 인스턴스

    Example:
        >>> embedder = get_embedder()
        >>> vectors = embedder.encode(["hello", "world"], "intfloat/multilingual-e5-large")
    """
    global _embedder_instance

    if _embedder_instance is None or force_new:
        # device가 None이면 config에서 로드
        if device is None:
            device = _load_device_from_config()

        _embedder_instance = Embedder(device=device)

    return _embedder_instance


def _load_device_from_config() -> Optional[str]:
    """
    ConfigManager를 사용하여 config에서 device 설정을 로드합니다.

    Returns:
        Optional[str]: config에서 읽은 device 설정, 없으면 None
    """
    try:
        from maru_lang.configs import get_config_manager

        config_manager = get_config_manager()
        merged_config = config_manager.get_embedder_config()

        if merged_config:
            return merged_config.device
    except ImportError:
        pass
    except Exception as e:
        print(f"⚠️ Embedder config 로드 실패: {e}")

    return None
