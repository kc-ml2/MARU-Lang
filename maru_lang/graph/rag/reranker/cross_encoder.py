"""CrossEncoder-based document compressor (LangChain BaseDocumentCompressor).

Config-free: all parameters are injected at construction time.
"""
import logging
from typing import Optional, Sequence

from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor
from langchain_core.callbacks import Callbacks
from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)

# Module-level model cache (shared across instances)
_model_cache: dict[str, CrossEncoder] = {}


def _get_or_load_model(model_name: str, device: Optional[str] = None) -> CrossEncoder:
    """Load or retrieve a cached CrossEncoder model."""
    cache_key = f"{model_name}:{device}"
    if cache_key not in _model_cache:
        logger.info(f"Loading reranker model: {model_name}...")
        _model_cache[cache_key] = CrossEncoder(model_name, device=device)
        device_info = f"device={device}" if device else "auto"
        logger.info(f"Reranker loaded: {model_name} ({device_info})")
    return _model_cache[cache_key]


def clear_model_cache() -> None:
    """Clear all cached CrossEncoder models."""
    count = len(_model_cache)
    _model_cache.clear()
    logger.info(f"Cleared {count} reranker model(s) from cache")


class CrossEncoderCompressor(BaseDocumentCompressor):
    """Rerank documents using a CrossEncoder model.

    All parameters are set at construction time — no config dependency.
    """

    model_name: str = "BAAI/bge-reranker-v2-m3"
    top_k: Optional[int] = None
    device: Optional[str] = None

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Callbacks = None,
    ) -> Sequence[Document]:
        if not documents:
            return documents

        model = _get_or_load_model(self.model_name, self.device)

        pairs = [[query, doc.page_content] for doc in documents]
        scores = model.predict(pairs)

        ranked = sorted(
            zip(documents, scores),
            key=lambda x: x[1],
            reverse=True,
        )

        if self.top_k is not None:
            ranked = ranked[: self.top_k]

        result = []
        for doc, score in ranked:
            doc_copy = doc.model_copy()
            doc_copy.metadata["reranker_score"] = float(score)
            result.append(doc_copy)

        return result
