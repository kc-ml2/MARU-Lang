"""Local ingest-to-Chroma end-to-end tests.

These tests use the real loader, splitter, ingest graph, and an isolated
Chroma collection. Only the embedding model is replaced with a deterministic
test double, so they require no model download or external service.
"""
from datetime import datetime
from unittest.mock import patch

import pytest

from maru_lang.core.vector_db.chroma import ChromaVectorDB
from maru_lang.core.relation_db.models.auth import Team
from maru_lang.core.relation_db.models.documents import Document
from maru_lang.enums.documents import DocumentStatus
from maru_lang.graph.ingest.graph import create_ingest_graph
from maru_lang.graph.ingest.state import build_ingest_input
from maru_lang.schemas.ingest import FileInfo
from maru_lang.services.team import delete_team


class DeterministicEmbeddings:
    """Return stable, non-zero vectors without loading an embedding model."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [
            [float(len(text) % 17 + 1), float(index + 1), 1.0]
            for index, text in enumerate(texts)
        ]


def _file_info(file_path) -> FileInfo:
    stat = file_path.stat()
    return FileInfo(
        fileName=file_path.name,
        createdAt=datetime.fromtimestamp(stat.st_mtime),
        absolutePath=str(file_path),
        size=stat.st_size,
    )


@pytest.mark.asyncio
async def test_real_ingest_then_team_delete_removes_orphans_only_for_target_team(
    tmp_path, team_with_admin, user_alice,
):
    """TXT ingest stores real chunk IDs, then team cleanup removes the right ones.

    This specifically protects the distinction between Chroma chunk IDs and
    relational document IDs that a mock-only team deletion test cannot catch.
    """
    other_team = await Team.create(
        name="OtherTeam", manager=user_alice, is_private=True,
    )
    team_to_delete = team_with_admin.id
    team_to_keep = other_team.id
    target_file = tmp_path / "target.txt"
    other_file = tmp_path / "other.txt"
    target_file.write_text(
        "Target team knowledge paragraph. " * 100,
        encoding="utf-8",
    )
    other_file.write_text(
        "Other team knowledge must survive deletion. " * 40,
        encoding="utf-8",
    )

    vdb = ChromaVectorDB(
        persist_dir=str(tmp_path / "chroma"),
        collection_name="ingest_team_delete_e2e",
    )
    graph = create_ingest_graph(vdb=vdb, embeddings=DeterministicEmbeddings())

    target_result = await graph.ainvoke(
        build_ingest_input(team_to_delete, file=_file_info(target_file))
    )
    other_result = await graph.ainvoke(
        build_ingest_input(team_to_keep, file=_file_info(other_file))
    )

    assert target_result["error"] is None
    assert other_result["error"] is None
    assert target_result["total_chunks"] > 1
    target_document_id = target_result["document"]["id"]
    other_document_id = other_result["document"]["id"]
    assert (await Document.get(id=target_document_id)).status == DocumentStatus.ACTIVE
    assert (await Document.get(id=other_document_id)).status == DocumentStatus.ACTIVE

    target_chunk_ids = vdb.collection.get(
        where={"team_id": team_to_delete}, include=[]
    )["ids"]
    other_chunk_ids = vdb.collection.get(
        where={"team_id": team_to_keep}, include=[]
    )["ids"]
    assert len(target_chunk_ids) == target_result["total_chunks"]
    assert len(other_chunk_ids) == other_result["total_chunks"]
    assert target_document_id not in target_chunk_ids

    # Simulate the exact final-sweep case: the relational row is already gone,
    # but its chunks remain orphaned in Chroma.
    await Document.filter(id=target_document_id).delete()
    with (
        patch("maru_lang.services.ingest.get_vector_db", return_value=vdb),
        patch("maru_lang.utils.file_storage.remove_team_storage"),
    ):
        await delete_team(team_to_delete, user_alice)

    assert not await Team.exists(id=team_to_delete)
    assert await Team.exists(id=team_to_keep)
    assert vdb.collection.get(
        where={"team_id": team_to_delete}, include=[]
    )["ids"] == []
    remaining_chunk_ids = vdb.collection.get(
        where={"team_id": team_to_keep}, include=[]
    )["ids"]
    assert set(remaining_chunk_ids) == set(other_chunk_ids)
    assert (await Document.get(id=other_document_id)).status == DocumentStatus.ACTIVE
