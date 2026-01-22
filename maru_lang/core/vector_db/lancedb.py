"""
LanceDB VectorDB Implementation
"""
import lancedb
from typing import Any, Optional
from pathlib import Path
from lancedb import DBConnection
from lancedb.table import Table
from maru_lang.core.vector_db.base import VectorDB
from maru_lang.core.vector_db.retrieve_document import RetrieveDocument


class LanceVectorDB(VectorDB):
    """
    LanceDB implementation of VectorDB interface

    LanceDB는 Apache Arrow 기반의 고성능 벡터 DB로,
    대용량 데이터에서도 빠른 검색 속도와 낮은 메모리 사용량을 제공합니다.
    """

    def __init__(
        self,
        persist_dir: str,
        table_name: str = "documents",
        embedding_dim: Optional[int] = None,
    ):
        """
        Initialize LanceDB VectorDB

        Args:
            persist_dir: Directory path for LanceDB storage
            table_name: Table name for storing documents
            embedding_dim: Dimension of embedding vectors (optional, inferred from first insert)
        """
        self.persist_dir = Path(persist_dir)
        self.table_name = table_name
        self.embedding_dim = embedding_dim

        # Create persist directory if not exists
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        # Connect to LanceDB
        self.db: DBConnection = lancedb.connect(str(self.persist_dir))

        # Try to open existing table, or will create on first add_documents
        try:
            self.table: Optional[Table] = self.db.open_table(table_name)
        except Exception:
            self.table = None

    def drop_collection(self) -> None:
        """
        Drop the table
        """
        if self.table_name in self.db.table_names():
            self.db.drop_table(self.table_name)
            self.table = None

    def add_documents(
        self,
        documents: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        """
        Add documents to LanceDB

        Args:
            documents: List of documents with id, content, metadata
            embeddings: List of embedding vectors
        """
        if not documents or not embeddings:
            return

        # Prepare data for LanceDB (pyarrow format)
        data = []
        for doc, embedding in zip(documents, embeddings):
            row = {
                "id": doc["id"],
                "content": doc["content"],
                "vector": embedding,
                # Flatten metadata into columns for better filtering
                **doc.get("metadata", {})
            }
            data.append(row)

        # Create or append to table
        if self.table is None:
            # Create new table
            self.table = self.db.create_table(self.table_name, data=data, mode="overwrite")
        else:
            # Append to existing table
            self.table.add(data)

    def sync_documents(self) -> None:
        """
        Sync documents - LanceDB handles persistence automatically
        """
        pass

    def has_document(self, doc_id: str) -> bool:
        """
        Check if document exists

        Args:
            doc_id: Document ID to check

        Returns:
            True if document exists
        """
        if self.table is None:
            return False

        try:
            results = self.table.search().where(f"id = '{doc_id}'").limit(1).to_list()
            return len(results) > 0
        except Exception:
            return False

    def update_document(
        self,
        doc_id: str,
        new_doc_id: str,
        new_content: str,
        embedding: list[float],
    ) -> None:
        """
        Update a document (delete old + add new)

        Args:
            doc_id: Original document ID
            new_doc_id: New document ID
            new_content: New content
            embedding: New embedding vector
        """
        # LanceDB doesn't support in-place updates
        # Delete old and add new
        self.delete_document(doc_id)

        # Get old metadata if exists
        old_metadata = {}
        try:
            results = self.table.search().where(f"id = '{doc_id}'").limit(1).to_list()
            if results:
                old_metadata = {k: v for k, v in results[0].items()
                              if k not in ["id", "content", "vector"]}
        except Exception:
            pass

        # Add new document
        self.add_documents(
            documents=[{
                "id": new_doc_id,
                "content": new_content,
                "metadata": old_metadata
            }],
            embeddings=[embedding]
        )

    def delete_document(self, doc_id: str) -> None:
        """
        Delete a document by ID

        Args:
            doc_id: Document ID to delete
        """
        if self.table is None:
            return

        try:
            self.table.delete(f"id = '{doc_id}'")
        except Exception as e:
            print(f"❌ Failed to delete document {doc_id}: {e}")

    def delete_all_chunks_by_document_id(self, document_id: str) -> int:
        """
        Delete all chunks by document ID

        Args:
            document_id: Document ID

        Returns:
            Number of chunks deleted
        """
        if self.table is None:
            return 0

        try:
            # Count before delete
            results = self.table.search().where(f"document_id = '{document_id}'").to_list()
            count = len(results)

            if count > 0:
                # Delete chunks
                self.table.delete(f"document_id = '{document_id}'")

            return count
        except Exception as e:
            print(f"❌ Failed to delete chunks for document {document_id}: {e}")
            return 0

    def upsert_documents(
        self,
        documents: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        """
        Add or update documents in LanceDB.

        Args:
            documents: List of documents with id, content, metadata
            embeddings: List of embedding vectors
        """
        if not documents or not embeddings:
            return

        # Prepare data for LanceDB
        data = []
        for doc, embedding in zip(documents, embeddings):
            row = {
                "id": doc["id"],
                "content": doc["content"],
                "vector": embedding,
                **doc.get("metadata", {})
            }
            data.append(row)

        if self.table is None:
            # Create new table
            self.table = self.db.create_table(self.table_name, data=data, mode="overwrite")
        else:
            # Delete existing documents with same IDs first
            for doc in documents:
                try:
                    self.table.delete(f"id = '{doc['id']}'")
                except Exception:
                    pass
            # Add new documents
            self.table.add(data)

    def get_chunk_ids_by_document_id(self, document_id: str) -> list[str]:
        """
        Get all chunk IDs for a document.

        Args:
            document_id: Document ID

        Returns:
            List of chunk IDs
        """
        if self.table is None:
            return []

        try:
            results = self.table.search().where(f"document_id = '{document_id}'").to_list()
            return [row["id"] for row in results]
        except Exception:
            return []

    def delete_chunks_by_ids(self, chunk_ids: list[str]) -> int:
        """
        Delete chunks by their IDs.

        Args:
            chunk_ids: List of chunk IDs to delete

        Returns:
            Number of deleted chunks
        """
        if self.table is None or not chunk_ids:
            return 0

        try:
            count = 0
            for chunk_id in chunk_ids:
                try:
                    self.table.delete(f"id = '{chunk_id}'")
                    count += 1
                except Exception:
                    pass
            return count
        except Exception:
            return 0

    def count_documents(self) -> int:
        """
        Count total documents

        Returns:
            Total document count
        """
        if self.table is None:
            return 0

        try:
            return self.table.count_rows()
        except Exception:
            return 0

    def get_all_metadata(self) -> list[dict]:
        """
        Get all document metadata

        Returns:
            List of metadata dictionaries
        """
        if self.table is None:
            return []

        try:
            results = self.table.search().to_list()
            return [
                {k: v for k, v in row.items() if k not in ["vector"]}
                for row in results
            ]
        except Exception:
            return []

    def get_documents(self, document_ids: list[str]) -> list[RetrieveDocument]:
        """
        Get specific documents by IDs

        Args:
            document_ids: List of document IDs to retrieve

        Returns:
            List of retrieved documents
        """
        if self.table is None or not document_ids:
            return []

        try:
            # Build WHERE clause
            ids_str = "', '".join(document_ids)
            where_clause = f"document_id IN ('{ids_str}')"

            results = self.table.search().where(where_clause).to_list()

            return [
                RetrieveDocument(
                    id=row["id"],
                    page_content=row["content"],
                    metadata={k: v for k, v in row.items()
                            if k not in ["id", "content", "vector"]}
                )
                for row in results
            ]
        except Exception as e:
            print(f"❌ Failed to get documents: {e}")
            return []

    def get_all_documents(
        self,
        team_ids: list[int]
    ) -> list[RetrieveDocument]:
        """
        Get all documents filtered by team IDs

        Args:
            team_ids: List of Team IDs to filter

        Returns:
            List of documents filtered by teams
        """
        if self.table is None or not team_ids:
            return []

        try:
            # Build WHERE clause for team_ids filtering
            ids_str = ", ".join(str(tid) for tid in team_ids)
            where_clause = f"team_id IN ({ids_str})"

            results = self.table.search().where(where_clause).to_list()

            return [
                RetrieveDocument(
                    id=row["id"],
                    page_content=row["content"],
                    metadata={k: v for k, v in row.items()
                            if k not in ["id", "content", "vector"]}
                )
                for row in results
            ]
        except Exception as e:
            print(f"❌ Failed to get all documents: {e}")
            return []

    def similarity_search(
        self,
        query_embedding: list[float],
        k: int,
        team_ids: list[int],
        **kwargs: dict[str, Any]
    ) -> list[RetrieveDocument]:
        """
        Vector similarity search

        Args:
            query_embedding: Query embedding vector
            k: Number of results to return
            team_ids: List of Team IDs to filter
            **kwargs: Additional search parameters

        Returns:
            List of retrieved documents with similarity scores
        """
        if self.table is None or not team_ids:
            return []

        try:
            # Build WHERE clause for team_ids filtering
            ids_str = ", ".join(str(tid) for tid in team_ids)
            where_clause = f"team_id IN ({ids_str})"

            # Perform vector search with filter
            results = (
                self.table.search(query_embedding)
                .where(where_clause)
                .limit(k)
                .to_list()
            )

            return [
                RetrieveDocument(
                    id=row["id"],
                    page_content=row["content"],
                    metadata={
                        **{k: v for k, v in row.items()
                           if k not in ["id", "content", "vector", "_distance"]},
                        "score": 1 - row.get("_distance", 0)  # Convert distance to similarity score
                    }
                )
                for row in results
            ]
        except Exception as e:
            print(f"❌ Similarity search failed: {e}")
            return []

    def hybrid_search(
        self,
        query_text: str,
        query_embedding: list[float],
        k: int,
        team_ids: list[int],
        **kwargs: dict[str, Any]
    ) -> list[RetrieveDocument]:
        """
        Hybrid search combining full-text search and vector similarity

        Args:
            query_text: Query text for full-text/FTS search
            query_embedding: Query embedding vector for similarity search
            k: Number of results to return
            team_ids: List of Team IDs to filter
            **kwargs: Additional search parameters

        Returns:
            List of retrieved documents with hybrid scores
        """
        if self.table is None or not team_ids:
            return []

        try:
            # Build WHERE clause for team_ids filtering
            ids_str = ", ".join(str(tid) for tid in team_ids)
            where_clause = f"team_id IN ({ids_str})"

            # LanceDB hybrid search with reranking
            results = (
                self.table.search(query_embedding, query_type="hybrid")
                .where(where_clause)
                .limit(k)
                .to_list()
            )

            return [
                RetrieveDocument(
                    id=row["id"],
                    page_content=row["content"],
                    metadata={
                        **{k: v for k, v in row.items()
                           if k not in ["id", "content", "vector", "_distance", "_relevance_score"]},
                        "score": row.get("_relevance_score", 1 - row.get("_distance", 0)),
                        "hybrid_score": True
                    }
                )
                for row in results
            ]
        except Exception as e:
            print(f"❌ Hybrid search failed: {e}")
            # Fallback to similarity search
            print("⚠️  Falling back to similarity_search")
            return self.similarity_search(query_embedding, k, team_ids, **kwargs)

    def health_check(self) -> bool:
        """
        LanceDB health check

        Returns:
            True if healthy

        Raises:
            Exception: If health check fails
        """
        # 1. Check if persist directory exists
        if not self.persist_dir.exists():
            raise FileNotFoundError(
                f"LanceDB directory not found: {self.persist_dir}\n"
                f"Physical VectorDB files are missing.\n"
                f"Please check your VectorDB configuration."
            )

        # 2. Check if we can access the database
        try:
            table_names = self.db.table_names()

            # If table exists, try to count rows
            if self.table_name in table_names:
                if self.table is None:
                    self.table = self.db.open_table(self.table_name)
                _ = self.table.count_rows()

            return True
        except Exception as e:
            raise RuntimeError(
                f"Failed to access LanceDB: {e}\n"
                f"Database may be corrupted. Please run 'chatbot remove <group>' and re-ingest."
            )
