"""
Ingest Pipeline - 파일을 ingest하는 파이프라인
"""
import asyncio
from pathlib import Path
from typing import List, Optional
from maru_lang.pipelines.base import BasePipeline, PipelineMessage
from maru_lang.core.relation_db.models.documents import Document, DocumentGroup
from maru_lang.enums.documents import DocumentStatus
from maru_lang.schemas.ingest import FileInfo
from maru_lang.services.document import (
    get_or_create_document_group,
    upsert_document_from_file,
    update_document_status,
)
from maru_lang.core.vector_db.factory import get_vector_db
from maru_lang.pluggable.loaders import get_loader
from maru_lang.pluggable.chunkers import get_chunker
from maru_lang.configs import get_config_manager
from maru_lang.pluggable.embedders import get_embedder
from maru_lang.models.vector_db import BaseVectorDBConfig
from maru_lang.models.ingest import IngestResult
from maru_lang.utils.document import make_chunk_uid


class IngestPipeline(BasePipeline):
    """파일 ingest 파이프라인"""

    def __init__(
        self,
        team_id: int,
        vdb_config: Optional[BaseVectorDBConfig] = None,
    ):
        super().__init__()
        self.team_id = team_id
        self.vdb = None
        self.vdb_config = vdb_config

        self.loader_manager = get_loader()
        self.chunker_manager = get_chunker()

        config_manager = get_config_manager()
        self.embedder_config = config_manager.get_embedder_config()
        if not self.embedder_config or not self.embedder_config.default_model:
            raise ValueError(
                "No embedding model configured. Please set default_model in embedder_config.yaml"
            )

    async def process(
        self,
        files: List[FileInfo],
        re_embed: bool = False,
    ):
        """파이프라인 메인 로직"""
        try:
            # 1. VDB 준비
            await self._prepare_vdb()

            # 2. Document 동기화 (그룹도 함께 생성)
            await self.queue.put(PipelineMessage.info(f"📄 Processing {len(files)} file(s)..."))
            all_documents, documents_to_process = await self._sync_documents(files, re_embed)

            # 4. 파싱/청킹/임베딩/VDB 저장
            failed_documents = await self._process_documents(documents_to_process)

            # 5. 결과 반환
            result = IngestResult(
                group=None,
                documents=all_documents,
                total_files=len(files),
                processed_files=len(documents_to_process),
                skipped_files=len(all_documents) - len(documents_to_process),
                failed_files=len(failed_documents),
                failed_details=failed_documents if failed_documents else None,
                deleted_files=0,
            )
            await self.queue.put(PipelineMessage.complete(data=result))

        except Exception as e:
            await self.queue.put(PipelineMessage.error(f"Pipeline failed: {str(e)}"))
            await self.queue.put(PipelineMessage.complete(data=None))
            raise

    async def _prepare_vdb(self):
        """VectorDB 준비"""
        self.vdb = get_vector_db(self.vdb_config)
        try:
            self.vdb.health_check()
            await self.queue.put(
                PipelineMessage.info(
                    f"💾 VDB connected (embedder: {self.embedder_config.default_model})")
            )
        except Exception as e:
            error_msg = f"❌ VectorDB health check failed: {str(e)}"
            await self.queue.put(PipelineMessage.error(error_msg))
            raise ValueError(error_msg)

    async def _sync_documents(
        self,
        files: List[FileInfo],
        re_embed: bool,
    ) -> tuple[list[Document], list[Document]]:
        """Document sync (also creates groups)"""
        all_documents = []
        documents_to_process = []
        # absolute_dir_path -> DocumentGroup
        group_cache: dict[str, DocumentGroup] = {}

        for file_info in files:
            try:
                # Use absolutePath for group hierarchy
                file_abs_path = Path(file_info.absolutePath).resolve()
                dir_abs_path = str(file_abs_path.parent)

                # Get or create group for this directory
                if dir_abs_path not in group_cache:
                    group = await self._get_or_create_group_for_abs_path(dir_abs_path, group_cache)
                else:
                    group = group_cache[dir_abs_path]

                doc, needs_processing = await upsert_document_from_file(
                    group=group,
                    name=Path(file_info.fileName).stem,
                    path=file_info.absolutePath,  # Store absolute path
                    size=file_info.size,
                    mtime_ns=int(file_info.createdAt.timestamp() * 1e9),
                    metadata={
                        "original_filename": file_info.fileName,
                        "temp_file_path": file_info.tempFilePath,
                    },
                )

                all_documents.append(doc)

                if re_embed or needs_processing:
                    documents_to_process.append(doc)

            except Exception as e:
                await self.queue.put(
                    PipelineMessage.warning(
                        f"Failed to sync {file_info.fileName}: {str(e)}")
                )

        return all_documents, documents_to_process

    async def _get_or_create_group_for_abs_path(
        self,
        abs_path: str,
        group_cache: dict[str, DocumentGroup],
    ) -> DocumentGroup:
        """Create group hierarchy based on absolute path"""
        if abs_path in group_cache:
            return group_cache[abs_path]

        path_obj = Path(abs_path)
        parts = path_obj.parts  # ('/', 'Users', 'jihoon', 'github', ...)

        # Build groups from root to current directory
        current_path = ""
        parent_group: DocumentGroup | None = None
        current_group: DocumentGroup | None = None

        for part in parts:
            if part == "/":
                continue  # Skip root slash

            current_path = current_path + "/" + part if current_path else "/" + part

            if current_path in group_cache:
                current_group = group_cache[current_path]
                parent_group = current_group
                continue

            current_group, _ = await get_or_create_document_group(
                team_id=self.team_id,
                name=part,
                parent=parent_group,
            )
            group_cache[current_path] = current_group
            parent_group = current_group

        # current_group should never be None for valid absolute paths
        assert current_group is not None, f"Invalid absolute path: {abs_path}"
        return current_group

    async def _process_documents(self, documents: list[Document]) -> dict:
        """Parse, chunk, embed, and store documents to VDB"""
        failed_documents = {}

        if not documents:
            await self.queue.put(PipelineMessage.info("No files to process"))
            return failed_documents

        embedder = get_embedder()
        total_chunks = 0

        for doc in documents:
            try:
                # Get file path (use temp_file_path from metadata if available)
                read_path = doc.metadata.get("temp_file_path") or doc.file_path
                file_path = Path(read_path)

                # Parse
                parse_result = self.loader_manager.parse(file_path)
                if not parse_result.content.strip():
                    await self.queue.put(PipelineMessage.warning(f"Empty content: {doc.name}"))
                    continue

                # Chunk
                chunker = self.chunker_manager.get_chunker_or_default(None)
                chunks = chunker.chunk(parse_result.content)
                if not chunks:
                    continue

                # Embed
                chunk_texts = [c.content for c in chunks]
                vectors = await asyncio.to_thread(
                    embedder.encode,
                    chunk_texts,
                    self.embedder_config.default_model,
                    show_progress=False
                )

                # Prepare VDB documents
                new_chunk_ids = set()
                vdb_docs = []
                for idx, chunk in enumerate(chunks):
                    chunk_id = make_chunk_uid(doc.id, idx, chunk.content)
                    new_chunk_ids.add(chunk_id)
                    vdb_docs.append({
                        "id": chunk_id,
                        "content": chunk.content,
                        "metadata": {
                            "document_id": doc.id,
                            "document_name": doc.name,
                            "team_id": self.team_id,
                            "file_path": doc.file_path or "",
                            "chunk_number": idx,
                        },
                    })

                # Upsert new chunks (add or update)
                await asyncio.to_thread(
                    self.vdb.upsert_documents,
                    documents=vdb_docs,
                    embeddings=vectors,
                )

                # Delete orphan chunks (old chunks not in new set)
                old_chunk_ids = set(await asyncio.to_thread(
                    self.vdb.get_chunk_ids_by_document_id,
                    doc.id
                ))
                orphan_ids = old_chunk_ids - new_chunk_ids
                if orphan_ids:
                    await asyncio.to_thread(
                        self.vdb.delete_chunks_by_ids,
                        list(orphan_ids)
                    )

                total_chunks += len(chunks)

                # Update status
                await update_document_status(doc, DocumentStatus.ACTIVE)
                await self.queue.put(PipelineMessage.info(f"  {doc.name}: {len(chunks)} chunks"))

            except Exception as e:
                failed_documents[doc.name] = str(e)
                await self.queue.put(PipelineMessage.error(f"  {doc.name}: {str(e)}"))

        await self.queue.put(
            PipelineMessage.info(
                f"Processed {len(documents) - len(failed_documents)} file(s), {total_chunks} chunks")
        )

        return failed_documents
