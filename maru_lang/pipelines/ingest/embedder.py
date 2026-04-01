"""LangChain 기반 Embedder - HuggingFace 임베딩"""
from typing import Optional
from langchain_huggingface import HuggingFaceEmbeddings

# 모델 캐시 (프로세스 단위)
_embeddings_cache: dict[str, HuggingFaceEmbeddings] = {}


def get_embeddings(
    model_name: str = "BAAI/bge-m3",
    device: Optional[str] = None,
) -> HuggingFaceEmbeddings:
    """HuggingFaceEmbeddings 인스턴스 반환 (캐시됨).

    Args:
        model_name: HuggingFace 모델 이름
        device: 디바이스 ("cpu", "cuda", "mps"). None이면 자동 감지.
    """
    cache_key = f"{model_name}:{device}"
    if cache_key not in _embeddings_cache:
        kwargs = {"model_name": model_name}
        if device:
            kwargs["model_kwargs"] = {"device": device}
        _embeddings_cache[cache_key] = HuggingFaceEmbeddings(**kwargs)
    return _embeddings_cache[cache_key]


def clear_cache():
    """임베딩 모델 캐시 초기화."""
    _embeddings_cache.clear()
