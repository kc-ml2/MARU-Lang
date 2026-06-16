"""HuggingFace-based embedder with per-process model caching."""
from typing import Optional
from langchain_huggingface import HuggingFaceEmbeddings

_embeddings_cache: dict[str, HuggingFaceEmbeddings] = {}


def get_embeddings(
    model_name: str = "BAAI/bge-m3",
    device: Optional[str] = None,
) -> HuggingFaceEmbeddings:
    """Return a cached HuggingFaceEmbeddings instance.

    Args:
        model_name: HuggingFace model name.
        device: Device ("cpu", "cuda", "mps"). None for auto-detect.
    """
    cache_key = f"{model_name}:{device}"
    if cache_key not in _embeddings_cache:
        kwargs = {"model_name": model_name}
        if device:
            kwargs["model_kwargs"] = {"device": device}
        _embeddings_cache[cache_key] = HuggingFaceEmbeddings(**kwargs)
    return _embeddings_cache[cache_key]


def clear_cache() -> None:
    """Clear the embedding model cache."""
    _embeddings_cache.clear()
