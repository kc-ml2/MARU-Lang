"""LLM-based reranker - uses an LLM to score document relevance."""
from typing import Any

from langchain_core.callbacks import Callbacks
from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor


class LLMReranker(BaseDocumentCompressor):
    """Rerank documents using an LLM to evaluate relevance scores."""

    llm: Any  # BaseChatModel — Any to avoid Pydantic validator issues with mocks
    top_k: int = 3

    def compress_documents(
        self,
        documents: list[Document],
        query: str,
        callbacks: Callbacks = None,
    ) -> list[Document]:
        if not documents:
            return []

        scored_docs = []
        for doc in documents:
            prompt = (
                f"Rate how relevant the following document is to the question "
                f"on a scale of 0-10. Answer with only a number.\n\n"
                f"Question: {query}\n\n"
                f"Document: {doc.page_content[:1000]}"
            )
            response = self.llm.invoke(prompt)
            try:
                score = float(response.content.strip())
            except (ValueError, AttributeError):
                score = 0.0
            scored_docs.append((score, doc))

        scored_docs.sort(key=lambda x: x[0], reverse=True)

        return [
            Document(
                page_content=doc.page_content,
                metadata={**doc.metadata, "reranker_score": score},
            )
            for score, doc in scored_docs[: self.top_k]
        ]
