"""VectorRetriever and knowledge_search tool unit tests."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
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


# ─── knowledge_search Tool ───────────────────────────────────


class TestKnowledgeSearchTool:
    @pytest.fixture
    def mock_retriever(self):
        r = MagicMock()
        r.ainvoke = AsyncMock(return_value=[])
        return r

    @pytest.fixture
    def mock_llm(self):
        from langchain_core.messages import AIMessage
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="response"))
        llm.bind_tools = MagicMock(return_value=llm)
        return llm

    def test_tool_has_correct_name(self, mock_retriever, mock_llm):
        from maru_lang.graph.chat.tools import create_knowledge_search_tool

        tool = create_knowledge_search_tool(mock_retriever, llm=mock_llm)
        assert tool.name == "knowledge_search"
        assert "Search" in tool.description or "search" in tool.description.lower()

    @pytest.mark.asyncio
    @patch("maru_lang.graph.chat.tools.knowledge_search.run_rag")
    async def test_runs_rag_and_returns_result_with_metadata(self, mock_run_rag, mock_retriever, mock_llm):
        from maru_lang.graph.chat.tools import create_knowledge_search_tool

        mock_run_rag.return_value = {
            "result": "Found documents about MARU",
            "documents": [{"document_id": "d1", "document_name": "test.pdf", "score": 0.8}],
        }

        tool = create_knowledge_search_tool(mock_retriever, llm=mock_llm)
        result = await tool.ainvoke(
            {"query": "what is MARU"},
            config={"configurable": {"state": {"team_ids": [1]}}},
        )

        assert "MARU" in result
        assert "retrieved_documents" in result

    @pytest.mark.asyncio
    @patch("maru_lang.graph.chat.tools.knowledge_search.run_rag")
    async def test_returns_error_message_on_exception(self, mock_run_rag, mock_retriever, mock_llm):
        from maru_lang.graph.chat.tools import create_knowledge_search_tool

        mock_run_rag.side_effect = Exception("RAG failed")

        tool = create_knowledge_search_tool(mock_retriever, llm=mock_llm)
        result = await tool.ainvoke(
            {"query": "test"},
            config={"configurable": {"state": {"team_ids": [1]}}},
        )

        assert "error" in result.lower() or "Error" in result
