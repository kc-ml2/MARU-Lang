"""Ingest graph nodes - single file sync and processing."""
import asyncio
from pathlib import Path

from maru_lang.graph.ingest.state import IngestState
from maru_lang.graph.ingest.loader import load_file
from maru_lang.graph.ingest.splitter import split_documents
from maru_lang.graph.ingest.embedder import get_embeddings
from maru_lang.core.vector_db import get_vector_db
from maru_lang.core.relation_db.models.documents import Document, DocumentGroup
from maru_lang.enums.documents import DocumentStatus
from maru_lang.services.document import (
    get_or_create_document_group,
    upsert_document_from_file,
    update_document_status,
)
from maru_lang.utils.document import make_chunk_uid


async def sync_document(state: IngestState) -> dict:
    """Step 1: Sync a single file to DB and create group hierarchy."""
    file_info = state["file"]
    team_id = state["team_id"]
    re_embed = state["re_embed"]

    try:
        file_abs_path = Path(file_info.absolutePath).resolve()
        dir_abs_path = str(file_abs_path.parent)

        group = await _get_or_create_group(dir_abs_path, team_id)

        doc, needs_processing = await upsert_document_from_file(
            group=group,
            name=Path(file_info.fileName).stem,
            path=file_info.absolutePath,
            size=file_info.size,
            mtime_ns=int(file_info.createdAt.timestamp() * 1e9),
            metadata={
                "original_filename": file_info.fileName,
            },
        )

        # Set storage_path if provided (API upload saves file first)
        if file_info.tempFilePath:
            doc.storage_path = file_info.tempFilePath
            await doc.save()

        document = {
            "id": doc.id,
            "name": doc.name,
            "file_path": doc.file_path,
            "storage_path": doc.storage_path,
            "group_id": doc.group_id,
            "metadata": doc.metadata,
        }

        return {
            "document": document,
            "needs_processing": re_embed or needs_processing,
            "messages": [f"Synced: {file_info.fileName}"],
        }

    except Exception as e:
        return {
            "document": None,
            "needs_processing": False,
            "error": str(e),
            "messages": [f"Failed to sync {file_info.fileName}: {e}"],
        }


async def process_document(state: IngestState) -> dict:
    """Step 2: Load -> Split -> Embed -> Store a single document."""
    doc = state["document"]
    team_id = state["team_id"]
    embedder_model = state["embedder_model"]

    if not doc or not state["needs_processing"]:
        return {"messages": ["Skipped (no processing needed)"]}

    # Update status to PROCESSING
    db_doc = await Document.get(id=doc["id"])
    await update_document_status(db_doc, DocumentStatus.PROCESSING)

    vdb = get_vector_db()
    embeddings = get_embeddings(model_name=embedder_model)

    try:
        # Read from storage_path (permanent) or file_path (original)
        read_path = doc.get("storage_path") or doc["file_path"]
        file_path = Path(read_path)

        lc_docs = await asyncio.to_thread(load_file, file_path)
        if not lc_docs or not any(d.page_content.strip() for d in lc_docs):
            await _set_error(db_doc, "Empty content")
            return {"messages": [f"Empty content: {doc['name']}"], "error": "Empty content"}

        chunks = await asyncio.to_thread(split_documents, lc_docs)
        if not chunks:
            await _set_error(db_doc, "No chunks produced")
            return {"messages": [f"No chunks: {doc['name']}"], "error": "No chunks"}

        chunk_texts = [c.page_content for c in chunks]
        vectors = await asyncio.to_thread(embeddings.embed_documents, chunk_texts)

        new_chunk_ids: set[str] = set()
        vdb_docs = []
        for idx, chunk in enumerate(chunks):
            chunk_id = make_chunk_uid(doc["id"], idx, chunk.page_content)
            new_chunk_ids.add(chunk_id)
            vdb_docs.append({
                "id": chunk_id,
                "content": chunk.page_content,
                "metadata": {
                    "document_id": doc["id"],
                    "document_name": doc["name"],
                    "team_id": team_id,
                    "group_id": doc["group_id"],
                    "file_path": doc["file_path"] or "",
                    "chunk_number": idx,
                },
            })

        await asyncio.to_thread(
            vdb.upsert_documents, documents=vdb_docs, embeddings=vectors
        )

        # Delete orphan chunks
        old_chunk_ids = set(
            await asyncio.to_thread(vdb.get_chunk_ids_by_document_id, doc["id"])
        )
        orphan_ids = old_chunk_ids - new_chunk_ids
        if orphan_ids:
            await asyncio.to_thread(vdb.delete_chunks_by_ids, list(orphan_ids))

        await update_document_status(db_doc, DocumentStatus.ACTIVE)

        return {
            "total_chunks": len(chunks),
            "messages": [f"{doc['name']}: {len(chunks)} chunks"],
        }

    except Exception as e:
        await _set_error(db_doc, str(e))
        return {
            "error": str(e),
            "messages": [f"{doc['name']}: ERROR - {e}"],
        }


async def _set_error(doc: Document, message: str) -> None:
    """Set document status to ERROR with message."""
    doc.status = DocumentStatus.ERROR
    doc.error_message = message
    await doc.save()


async def _get_or_create_group(
    abs_path: str,
    team_id: int,
) -> DocumentGroup:
    """Create a DocumentGroup hierarchy based on absolute path."""
    path_obj = Path(abs_path)
    parts = path_obj.parts

    current_path = ""
    parent_group = None
    current_group = None

    for part in parts:
        if part == "/":
            continue
        current_path = current_path + "/" + part if current_path else "/" + part

        current_group, _ = await get_or_create_document_group(
            team_id=team_id, name=part, parent=parent_group,
        )
        parent_group = current_group

    assert current_group is not None, f"Invalid absolute path: {abs_path}"
    return current_group
