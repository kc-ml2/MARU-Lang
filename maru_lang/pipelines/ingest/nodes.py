"""Ingest Pipeline Nodes - LangGraph 노드 함수"""
import asyncio
from pathlib import Path

from maru_lang.pipelines.ingest.state import IngestState
from maru_lang.pipelines.ingest.loader import load_file
from maru_lang.pipelines.ingest.splitter import split_documents
from maru_lang.pipelines.ingest.embedder import get_embeddings
from maru_lang.core.vector_db.factory import get_vector_db
from maru_lang.core.relation_db.models.documents import DocumentGroup
from maru_lang.enums.documents import DocumentStatus
from maru_lang.services.document import (
    get_or_create_document_group,
    upsert_document_from_file,
    update_document_status,
)
from maru_lang.utils.document import make_chunk_uid


async def sync_documents(state: IngestState) -> dict:
    """Step 1: Document DB 동기화 (그룹 계층 구조 생성)"""
    files = state["files"]
    team_id = state["team_id"]
    re_embed = state["re_embed"]

    all_documents = []
    documents_to_process = []
    group_cache: dict[str, DocumentGroup] = {}
    messages = [f"Processing {len(files)} file(s)..."]

    for file_info in files:
        try:
            file_abs_path = Path(file_info.absolutePath).resolve()
            dir_abs_path = str(file_abs_path.parent)

            if dir_abs_path not in group_cache:
                group = await _get_or_create_group(dir_abs_path, team_id, group_cache)
            else:
                group = group_cache[dir_abs_path]

            doc, needs_processing = await upsert_document_from_file(
                group=group,
                name=Path(file_info.fileName).stem,
                path=file_info.absolutePath,
                size=file_info.size,
                mtime_ns=int(file_info.createdAt.timestamp() * 1e9),
                metadata={
                    "original_filename": file_info.fileName,
                    "temp_file_path": file_info.tempFilePath,
                },
            )

            all_documents.append({
                "id": doc.id,
                "name": doc.name,
                "file_path": doc.file_path,
                "group_id": doc.group_id,
                "metadata": doc.metadata,
            })

            if re_embed or needs_processing:
                documents_to_process.append({
                    "id": doc.id,
                    "name": doc.name,
                    "file_path": doc.file_path,
                    "group_id": doc.group_id,
                    "metadata": doc.metadata,
                })

        except Exception as e:
            messages.append(f"Failed to sync {file_info.fileName}: {e}")

    return {
        "all_documents": all_documents,
        "documents_to_process": documents_to_process,
        "messages": messages,
    }


async def process_documents(state: IngestState) -> dict:
    """Step 2: Load → Split → Embed → Store"""
    docs = state["documents_to_process"]
    team_id = state["team_id"]
    embedder_model = state["embedder_model"]

    if not docs:
        return {"messages": ["No files to process"]}

    vdb = get_vector_db(state.get("vdb_config"))
    embeddings = get_embeddings(model_name=embedder_model)

    failed_documents = {}
    total_chunks = 0
    processed_count = 0
    messages = []

    for doc in docs:
        try:
            read_path = doc["metadata"].get("temp_file_path") or doc["file_path"]
            file_path = Path(read_path)

            # 1. Load
            lc_docs = await asyncio.to_thread(load_file, file_path)
            if not lc_docs or not any(d.page_content.strip() for d in lc_docs):
                messages.append(f"Empty content: {doc['name']}")
                continue

            # 2. Split
            chunks = await asyncio.to_thread(split_documents, lc_docs)
            if not chunks:
                continue

            # 3. Embed
            chunk_texts = [c.page_content for c in chunks]
            vectors = await asyncio.to_thread(embeddings.embed_documents, chunk_texts)

            # 4. Store
            new_chunk_ids = set()
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

            # 고아 청크 삭제
            old_chunk_ids = set(
                await asyncio.to_thread(vdb.get_chunk_ids_by_document_id, doc["id"])
            )
            orphan_ids = old_chunk_ids - new_chunk_ids
            if orphan_ids:
                await asyncio.to_thread(vdb.delete_chunks_by_ids, list(orphan_ids))

            total_chunks += len(chunks)
            processed_count += 1

            from maru_lang.core.relation_db.models.documents import Document
            db_doc = await Document.get(id=doc["id"])
            await update_document_status(db_doc, DocumentStatus.ACTIVE)

            messages.append(f"  {doc['name']}: {len(chunks)} chunks")

        except Exception as e:
            failed_documents[doc["name"]] = str(e)
            messages.append(f"  {doc['name']}: ERROR - {e}")

    messages.append(f"Processed {processed_count} file(s), {total_chunks} chunks")

    return {
        "processed_count": processed_count,
        "failed_documents": failed_documents,
        "total_chunks": total_chunks,
        "messages": messages,
    }


# ─── Helper ──────────────────────────────────────────────────

async def _get_or_create_group(
    abs_path: str,
    team_id: int,
    group_cache: dict[str, DocumentGroup],
) -> DocumentGroup:
    """절대 경로 기반 DocumentGroup 계층 구조 생성"""
    if abs_path in group_cache:
        return group_cache[abs_path]

    path_obj = Path(abs_path)
    parts = path_obj.parts

    current_path = ""
    parent_group = None
    current_group = None

    for part in parts:
        if part == "/":
            continue
        current_path = current_path + "/" + part if current_path else "/" + part

        if current_path in group_cache:
            current_group = group_cache[current_path]
            parent_group = current_group
            continue

        current_group, _ = await get_or_create_document_group(
            team_id=team_id, name=part, parent=parent_group,
        )
        group_cache[current_path] = current_group
        parent_group = current_group

    assert current_group is not None, f"Invalid absolute path: {abs_path}"
    return current_group
