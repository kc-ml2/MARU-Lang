"""VectorRetriever unit tests."""
import pytest
from unittest.mock import MagicMock
from langchain_core.documents import Document


# ─── VectorRetriever ─────────────────────────────────────────


class TestVectorRetriever:
    def test_returns_empty_when_no_team_ids(self):
        from maru_lang.graph.rag.retriever.vector import VectorRetriever

        mock_vdb = MagicMock()
        mock_emb = MagicMock()

        retriever = VectorRetriever(vdb=mock_vdb, embeddings=mock_emb, team_ids=[])
        run_manager = MagicMock()
        result = retriever._get_relevant_documents("query", run_manager=run_manager)
        assert result == []

    def test_vector_search_calls_vdb(self):
        from maru_lang.graph.rag.retriever.vector import VectorRetriever

        mock_vdb = MagicMock()
        mock_vdb.similarity_search.return_value = [Document(page_content="hit")]
        mock_emb = MagicMock()
        mock_emb.embed_query.return_value = [0.1] * 384

        retriever = VectorRetriever(
            vdb=mock_vdb, embeddings=mock_emb,
            team_ids=[1], search_method="vector",
        )
        run_manager = MagicMock()
        result = retriever._get_relevant_documents("query", run_manager=run_manager)

        assert len(result) == 1
        mock_vdb.similarity_search.assert_called_once()

    def test_hybrid_search_calls_vdb(self):
        from maru_lang.graph.rag.retriever.vector import VectorRetriever

        mock_vdb = MagicMock()
        mock_vdb.hybrid_search.return_value = [Document(page_content="hit")]
        mock_emb = MagicMock()
        mock_emb.embed_query.return_value = [0.1] * 384

        retriever = VectorRetriever(
            vdb=mock_vdb, embeddings=mock_emb,
            team_ids=[1], search_method="hybrid",
        )
        run_manager = MagicMock()
        result = retriever._get_relevant_documents("query", run_manager=run_manager)

        assert len(result) == 1
        mock_vdb.hybrid_search.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_vector_search(self):
        """Ensures async path uses asyncio.to_thread to avoid event loop blocking."""
        from maru_lang.graph.rag.retriever.vector import VectorRetriever

        mock_vdb = MagicMock()
        mock_vdb.similarity_search.return_value = [Document(page_content="hit")]
        mock_emb = MagicMock()
        mock_emb.embed_query.return_value = [0.1] * 384

        retriever = VectorRetriever(
            vdb=mock_vdb, embeddings=mock_emb,
            team_ids=[1], search_method="vector",
        )
        run_manager = MagicMock()
        result = await retriever._aget_relevant_documents("query", run_manager=run_manager)

        assert len(result) == 1

    def test_handles_vdb_exception(self):
        from maru_lang.graph.rag.retriever.vector import VectorRetriever

        mock_vdb = MagicMock()
        mock_vdb.similarity_search.side_effect = Exception("VDB error")
        mock_emb = MagicMock()
        mock_emb.embed_query.return_value = [0.1] * 384

        retriever = VectorRetriever(
            vdb=mock_vdb, embeddings=mock_emb,
            team_ids=[1], search_method="vector",
        )
        run_manager = MagicMock()
        result = retriever._get_relevant_documents("query", run_manager=run_manager)
        assert result == []
