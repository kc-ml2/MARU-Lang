"""Compressed retriever - retriever + compressor composition.

Replaces langchain's ContextualCompressionRetriever with a simple
implementation that has no external dependency.
"""
import asyncio

from langchain_core.callbacks import CallbackManagerForRetrieverRun, AsyncCallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor
from langchain_core.retrievers import BaseRetriever
from pydantic import Field


class CompressedRetriever(BaseRetriever):
    """Retriever that applies a compressor/reranker to base retriever results."""

    base_retriever: BaseRetriever
    compressor: BaseDocumentCompressor

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        docs = self.base_retriever.invoke(query)
        return list(self.compressor.compress_documents(docs, query))

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: AsyncCallbackManagerForRetrieverRun,
    ) -> list[Document]:
        docs = await self.base_retriever.ainvoke(query)
        return list(await asyncio.to_thread(
            self.compressor.compress_documents, docs, query
        ))
