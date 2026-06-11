"""CrossEncoder-based document compressor (LangChain BaseDocumentCompressor).

Config-free: all parameters are injected at construction time.
"""
import logging
import threading
from typing import Optional, Sequence

from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor
from langchain_core.callbacks import Callbacks
from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)

# Module-level model cache (shared across instances). Access is guarded by
# `_cache_lock` because callers now run inside `asyncio.to_thread` — concurrent
# first-hits would otherwise load duplicate heavyweight models and spike memory.
_model_cache: dict[str, CrossEncoder] = {}
_cache_lock = threading.Lock()
# Per-key inference locks serialize `model.predict` on the same cached model,
# since CrossEncoder/sentence-transformers models are not guaranteed thread-safe
# for concurrent inference.
_inference_locks: dict[str, threading.Lock] = {}


def _get_or_load_model(model_name: str, device: Optional[str] = None) -> CrossEncoder:
    """Load or retrieve a cached CrossEncoder model (thread-safe)."""
    cache_key = f"{model_name}:{device}"
    # Double-checked locking: fast path avoids the lock on cache hit.
    model = _model_cache.get(cache_key)
    if model is not None:
        return model
    with _cache_lock:
        model = _model_cache.get(cache_key)
        if model is None:
            logger.info(f"Loading reranker model: {model_name}...")
            model = CrossEncoder(model_name, device=device)
            device_info = f"device={device}" if device else "auto"
            logger.info(f"Reranker loaded: {model_name} ({device_info})")
            _model_cache[cache_key] = model
            _inference_locks[cache_key] = threading.Lock()
    return model


def _get_inference_lock(model_name: str, device: Optional[str]) -> threading.Lock:
    return _inference_locks[f"{model_name}:{device}"]


def clear_model_cache() -> None:
    """Clear all cached CrossEncoder models."""
    with _cache_lock:
        count = len(_model_cache)
        _model_cache.clear()
        _inference_locks.clear()
    logger.info(f"Cleared {count} reranker model(s) from cache")


class CrossEncoderCompressor(BaseDocumentCompressor):
    """Rerank documents using a CrossEncoder model.

    All parameters are set at construction time — no config dependency.
    """

    model_name: str = "BAAI/bge-reranker-v2-m3"
    top_k: Optional[int] = None
    device: Optional[str] = None
    # Drop documents scoring below this (issue #1). Raw cross-encoder scores are
    # model-dependent, so the cutoff is opt-in (None = keep all).
    min_score: Optional[float] = None

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Callbacks = None,
    ) -> Sequence[Document]:
        if not documents:
            return documents

        model = _get_or_load_model(self.model_name, self.device)
        inference_lock = _get_inference_lock(self.model_name, self.device)

        pairs = [[query, doc.page_content] for doc in documents]
        # Serialize inference on the shared cached model: sentence-transformers
        # CrossEncoder is not documented as thread-safe and `asyncio.to_thread`
        # can dispatch this method concurrently.
        with inference_lock:
            scores = model.predict(pairs)

        ranked = sorted(
            zip(documents, scores),
            key=lambda x: x[1],
            reverse=True,
        )

        if self.min_score is not None:
            ranked = [(doc, s) for doc, s in ranked if s >= self.min_score]

        if self.top_k is not None:
            ranked = ranked[: self.top_k]

        result = []
        for doc, score in ranked:
            doc_copy = doc.model_copy()
            doc_copy.metadata["reranker_score"] = float(score)
            result.append(doc_copy)

        return result
