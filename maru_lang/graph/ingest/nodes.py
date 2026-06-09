"""Ingest graph nodes - single file sync, parsing, and processing."""
import asyncio
from pathlib import Path

from langchain_core.documents import Document as LCDocument

from maru_lang.graph.ingest.state import IngestState
from maru_lang.graph.ingest.parser import parse_file
from maru_lang.graph.ingest.splitter import split_documents
from maru_lang.core.relation_db.models.documents import Document
from maru_lang.enums.documents import DocumentStatus
from maru_lang.services.document import (
    get_or_create_group_hierarchy,
    upsert_document_from_file,
    update_document_status,
    set_document_error,
)
from maru_lang.utils.document import make_chunk_uid


async def sync_document(state: IngestState) -> dict:
    """Step 1: Sync a single file to DB and create group hierarchy.

    When `document` is already in the state (API upload / ARQ worker, where the
    record and group were created before enqueue), there is nothing to sync —
    pass through so the same graph serves both entry shapes.
    """
    if state.get("document") is not None:
        return {"messages": ["Already synced"]}

    file_info = state["file"]
    team_id = state["team_id"]
    re_embed = state["re_embed"]

    try:
        file_abs_path = Path(file_info.absolutePath).resolve()
        dir_abs_path = str(file_abs_path.parent)

        group = await get_or_create_group_hierarchy(dir_abs_path, team_id)

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


async def parse_document(state: IngestState) -> dict:
    """Step 2: Parse a document (KorDoc MCP or LangChain).

    Picks the parser per maru_config (KorDoc-supported formats via the KorDoc MCP
    server, others via the LangChain loaders) and records which parser produced
    the document in metadata.
    """
    doc = state["document"]

    if not doc or not state["needs_processing"]:
        return {"parsed_docs": None, "messages": ["Skipped (no processing needed)"]}

    # Document가 삭제되었는지 확인 후 상태 전환
    db_doc = await Document.get_or_none(id=doc["id"])
    if not db_doc:
        return {"parsed_docs": None, "messages": [f"Skipped (document deleted): {doc['name']}"]}

    await update_document_status(db_doc, DocumentStatus.PROCESSING)

    try:
        # Read from storage_path (permanent) or file_path (original)
        read_path = doc.get("storage_path") or doc["file_path"]
        file_path = Path(read_path)

        lc_docs, parser = await parse_file(file_path, doc["id"])
        if not lc_docs or not any(d.page_content.strip() for d in lc_docs):
            await set_document_error(db_doc, "Empty content")
            return {
                "parsed_docs": None,
                "error": "Empty content",
                "messages": [f"Empty content ({parser}): {doc['name']}"],
            }

        # 어느 파서로 생성됐는지 metadata에 기록
        db_doc.metadata = {**(db_doc.metadata or {}), "parser": parser}
        await db_doc.save()

        parsed_docs = [
            {"content": d.page_content, "metadata": d.metadata or {}}
            for d in lc_docs
        ]
        return {
            "parsed_docs": parsed_docs,
            "parser": parser,
            "messages": [f"Parsed ({parser}): {doc['name']}"],
        }

    except Exception as e:
        if await Document.exists(id=doc["id"]):
            await set_document_error(db_doc, str(e))
        return {
            "parsed_docs": None,
            "error": str(e),
            "messages": [f"{doc['name']}: PARSE ERROR - {e}"],
        }


def make_process_document_node(vdb, embeddings):
    """Build the process_document node with its vector DB + embeddings injected.

    These are the only heavy, process-stable dependencies in the ingest graph,
    so (like the RAG graph's model-bearing nodes) they're built once at graph
    construction and closed over rather than looked up per call.
    """

    async def process_document(state: IngestState) -> dict:
        """Step 3: Split -> Embed -> Store parsed content."""
        doc = state["document"]
        team_id = state["team_id"]
        parsed_docs = state.get("parsed_docs")

        if not doc or not parsed_docs:
            return {"messages": ["Skipped (nothing to process)"]}

        # parse 노드 이후 삭제되었는지 재확인
        db_doc = await Document.get_or_none(id=doc["id"])
        if not db_doc:
            return {"messages": [f"Skipped (document deleted): {doc['name']}"]}

        try:
            lc_docs = [
                LCDocument(page_content=p["content"], metadata=p.get("metadata") or {})
                for p in parsed_docs
            ]
            chunks = await asyncio.to_thread(split_documents, lc_docs)
            if not chunks:
                await set_document_error(db_doc, "No chunks produced")
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

            # embedding 완료 후 삭제 여부 재확인 — 삭제된 문서를 ACTIVE로 되살리지 않음
            if not await Document.exists(id=doc["id"]):
                # 처리 중 삭제됨 → VectorDB에 넣은 청크도 정리
                try:
                    await asyncio.to_thread(vdb.delete_all_chunks_by_document_id, doc["id"])
                except Exception:
                    pass
                return {"messages": [f"Aborted (document deleted during processing): {doc['name']}"]}

            await update_document_status(db_doc, DocumentStatus.ACTIVE)

            return {
                "total_chunks": len(chunks),
                "messages": [f"{doc['name']}: {len(chunks)} chunks"],
            }

        except Exception as e:
            # 에러 기록 전 문서 존재 여부 확인 — 삭제된 문서에 에러 상태를 쓰지 않음
            if await Document.exists(id=doc["id"]):
                await set_document_error(db_doc, str(e))
            return {
                "error": str(e),
                "messages": [f"{doc['name']}: ERROR - {e}"],
            }

    return process_document
