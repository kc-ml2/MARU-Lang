"""
Ingest Pipeline - 로컬 파일 시스템을 ingest하는 파이프라인
"""
import asyncio
from pathlib import Path
from typing import List, Optional, Tuple
from maru_lang.pipelines.base import BasePipeline, PipelineMessage
from maru_lang.core.relation_db.models.documents import (
    Document,
    DocumentGroup,
    DocumentGroupMembership,
    DocumentGroupInclusion,
)
from maru_lang.enums.documents import DocumentStatus, SyncMode
from maru_lang.schemas.ingest import FileInfo
from maru_lang.services.document import (
    upsert_document_group,
    set_document_group_inclusion,
    upsert_document_from_file,
    update_document_status,
)
from maru_lang.core.vector_db.factory import get_vector_db, VectorDB
from maru_lang.configs.system_config import get_system_config
from maru_lang.pluggable.loaders import get_loader
from maru_lang.pluggable.chunkers import get_chunker
from maru_lang.configs import get_config_manager
from maru_lang.pluggable.embedders import get_embedder, Embedder
from maru_lang.models.vector_db import BaseVectorDBConfig
from maru_lang.models.ingest import IngestResult
from maru_lang.utils.document import make_chunk_uid

config = get_system_config()


class IngestPipeline(BasePipeline):
    """로컬 파일 시스템 ingest 파이프라인"""

    def __init__(
        self,
        files: List[FileInfo],
        group_name: str,
        manager_id: int,
        base_path: Path,
        vdb_config: BaseVectorDBConfig = None,
        re_embed: bool = False,
        description: Optional[str] = None,
    ):
        """
        Args:
            files: ingest할 파일 리스트 (FileInfo 객체들)
            group_name: 최상위 DocumentGroup 이름
            vdb_config: VectorDB 설정 (ChromaDB, Milvus 등)
            manager_id: 관리자 User ID
            base_path: DocumentGroup의 base_path (DB 저장용, 그룹 계층 구조 결정)
            re_embed: 기존 임베딩을 삭제하고 처음부터 다시 임베딩할지 여부
            description: DocumentGroup 설명
        """
        super().__init__()
        self.files = files
        self.base_path = base_path  # DocumentGroup의 base_path
        self.group_name = group_name
        self.vdb_config = vdb_config
        self.manager_id = manager_id
        self.re_embed = re_embed
        self.description = description

        # Config-driven 컴포넌트 로드
        config_manager = get_config_manager()
        config_manager.ensure_loaded()
        self.loader_manager = get_loader()
        self.chunker_manager = get_chunker()

        # RAG config 로드 (그룹별 설정 조회용)
        # ConfigManager는 lazy loading이므로 명시적으로 로드 필요
        self.rag_config = config_manager.get_rag_config()

        # Embedding model 설정 저장
        self.embedder_config = config_manager.get_embedder_config()
        if not self.embedder_config or not self.embedder_config.default_model:
            raise ValueError(
                "No embedding model configured. Please set default_model in embedder_config.yaml"
            )
        # VectorDB 인스턴스 (CRUD 직접 사용)
        self.vdb = None

    # ========== Pipeline Process ==========

    async def process(self):
        """파이프라인 주요 로직"""
        try:
            await self.queue.put(PipelineMessage.info("🏗️  Syncing group hierarchy..."))

            # 1. 그룹 계층 정보 수집
            unique_groups, parent_child_pairs, file_hierarchies = await self._get_group_hierarchy()

            # 2. 그룹 생성 및 설정 변경 감지
            group_mapping, changed_groups = await self._create_groups(unique_groups)

            # 3. 부모-자식 관계 설정
            await self._set_group_relationships(parent_child_pairs, group_mapping)

            # 4. Document 생성 및 연결 (및 삭제된 파일 제거)
            all_documents, documents_to_process, deleted_count = await self._sync_documents(file_hierarchies, group_mapping, changed_groups)

            # 5. VDB 설정
            await self._prepare_processing()

            # 6. 파싱, 청킹, 임베딩, VDB 저장, 상태 업데이트
            failed_documents = await self._process_documents(documents_to_process)

            # 7. 완료 - Create result and send via queue
            root_group = group_mapping.get(self._get_base_path_str())
            result = IngestResult(
                group=root_group,
                documents=all_documents,
                total_files=len(self.files) if self.files else 0,
                processed_files=len(documents_to_process),
                skipped_files=len(all_documents) - len(documents_to_process),
                failed_files=len(failed_documents),
                failed_details=failed_documents if failed_documents else None,
                deleted_files=deleted_count,
            )
            await self.queue.put(PipelineMessage.complete(data=result))

        except Exception as e:
            await self.queue.put(PipelineMessage.error(f"Pipeline failed: {str(e)}"))
            await self.queue.put(PipelineMessage.complete(data=None))
            raise

    # ========== VectorDB 설정 ==========

    async def _prepare_processing(self):
        """VectorDB 인스턴스 생성 (CRUD 직접 사용)"""
        # VectorDB 팩토리로 인스턴스 생성
        self.vdb = get_vector_db(self.vdb_config)

        # 헬스체크 수행
        try:
            self.vdb.health_check()
            await self.queue.put(
                PipelineMessage.info(
                    f"💾 VDB connected (embedder: {self.embedder_config.default_model})"
                )
            )
        except Exception as e:
            error_msg = (
                f"❌ VectorDB health check failed:\n"
                f"{str(e)}\n\n"
                f"Check your VectorDB configuration"
            )
            await self.queue.put(PipelineMessage.error(error_msg))
            raise ValueError(error_msg)

    # ========== Helper Methods ==========

    def _get_base_path_str(self) -> str:
        """
        Get base path string for DocumentGroup.
        Uses base_path for DB storage.
        """
        return str(self.base_path.absolute())

    def _get_group_rag_components(self, group_name: str) -> dict:
        """
        그룹별 RAG config 조회
        """

        # 그룹별 RAG config 조회
        loader_name = None
        chunker_name = None
        embedding_model = self.embedder_config.default_model

        if self.rag_config:
            group_config = self.rag_config.groups.get(group_name)
            if group_config and group_config.components:
                loader_name = group_config.components.loader
                chunker_name = group_config.components.chunker
                embedding_model = group_config.components.embedding_model

        return {
            "loader": loader_name,
            "chunker": chunker_name,
            "embedding_model": embedding_model,
        }

    def _get_group_hierarchy_for_file(
        self,
        relative_path: str
    ) -> List[tuple[Optional[str], str, str]]:
        """
        파일의 그룹 계층 구조를 결정

        Returns:
            List of (parent_path, name, current_path) tuples
            - parent_path: 부모 그룹의 base_path (None이면 최상위)
            - name: 현재 그룹의 full path 이름 (unique 식별자)
            - current_path: 현재 그룹의 base_path
        """
        relative_path = Path(relative_path)
        parts = relative_path.parts[:-1]  # 파일명 제외

        base_path_str = self._get_base_path_str()

        # 최상위 그룹 (base)
        if not parts:
            return [(None, self.group_name, base_path_str)]

        hierarchy = [(None, self.group_name, base_path_str)]

        # 하위 그룹들
        for i, _ in enumerate(parts):
            # base_path 기준으로 경로 구성
            current_path = self.base_path / Path(*parts[: i + 1])
            current_path_str = str(current_path.absolute())

            # 부모 경로
            if i == 0:
                parent_path_str = base_path_str
            else:
                parent_path = self.base_path / Path(*parts[:i])
                parent_path_str = str(parent_path.absolute())

            subpath = "/".join(parts[: i + 1])
            name = f"{self.group_name}/{subpath}"

            hierarchy.append((parent_path_str, name, current_path_str))

        return hierarchy

    # ========== DocumentGroup 계층 동기화 ==========

    async def _get_group_hierarchy(self):
        """
        Get group hierarchy for all files.
        """
        groups = {}
        file_hierarchies = []
        parent_child_pairs = set()
        for f in self.files:
            hierarchy = self._get_group_hierarchy_for_file(f.relativePath)
            file_hierarchies.append((f, hierarchy))

        # 2. 고유한 그룹들과 부모-자식 관계 추출
        for _, hierarchy in file_hierarchies:
            for parent_path, name, current_path in hierarchy:
                groups[current_path] = name
                if parent_path:
                    parent_child_pairs.add((parent_path, current_path))

        return groups, parent_child_pairs, file_hierarchies

    async def _create_groups(
        self,
        unique_groups: dict,
        sync_mode: SyncMode = SyncMode.SERVER
    ):
        """
        그룹 생성 및 설정 변경 감지

        Returns:
            tuple: (group_mapping, changed_groups)
                - group_mapping: dict (path -> DocumentGroup)
                - changed_groups: set of group names that had config changes
        """
        group_mapping = {}
        changed_groups = set()

        for path, name in unique_groups.items():
            rag_components = self._get_group_rag_components(name)

            group, created, config_changed = await upsert_document_group(
                name=name,
                base_path=path,
                manager_id=self.manager_id,
                rag_components=rag_components,
                force_new_version=self.re_embed,
                description=self.description if (
                    name == self.group_name) else None,
                sync_mode=sync_mode,
            )
            group_mapping[path] = group

            # 신규 생성, 설정 변경, 또는 re_embed가 활성화된 경우 changed로 표시
            if created or config_changed or self.re_embed:
                changed_groups.add(name)

        return group_mapping, changed_groups

    async def _set_group_relationships(self, parent_child_pairs: set, group_mapping: dict):
        """
        부모-자식 관계 설정
        """
        for parent_path, child_path in parent_child_pairs:
            await set_document_group_inclusion(
                group_mapping[parent_path], group_mapping[child_path]
            )

    async def _sync_documents(self, file_hierarchies: list, group_mapping: dict, changed_groups: set):
        """
        Document 생성 및 그룹 연결

        Args:
            file_hierarchies: 파일 정보 및 계층 구조
            group_mapping: path -> DocumentGroup 매핑
            changed_groups: 설정이 변경된 그룹 이름들

        Returns:
            tuple: (all_documents, documents_to_process)
        """
        all_documents = []
        documents_to_process = []

        for file_info, hierarchy in file_hierarchies:
            try:
                # FileInfo로부터 파일 경로 생성
                file_path = self.base_path / file_info.relativePath
                # 1. Document 생성 및 변경 감지
                doc, needs_reprocessing = await upsert_document_from_file(
                    name=Path(file_info.fileName).stem,
                    path=str(file_path.absolute()),
                    size=file_info.size,
                    mtime_ns=int(file_info.createdAt.timestamp() * 1e9),
                    metadata={"original_filename": file_info.fileName},
                )

                # 2. 파일의 최종 그룹 결정
                final_group_path = hierarchy[-1][2]

                # 3. DocumentGroup 연결
                doc_group = group_mapping[final_group_path]
                await DocumentGroupMembership.get_or_create(
                    document=doc, group=doc_group
                )

                # 4. Store hierarchical group info and temp path in document metadata
                group_path_parts = [h[1]
                                    # h[1] = name (full path)
                                    for h in hierarchy]
                hierarchical_group_name = "_".join(group_path_parts)
                doc.metadata = {
                    **(doc.metadata or {}),
                    "hierarchical_group_name": hierarchical_group_name,
                    "group_version_id": doc_group.version_id,
                }
                # Store tempFilePath if available (for parsing uploaded files)
                if file_info.tempFilePath:
                    doc.metadata["temp_file_path"] = file_info.tempFilePath
                await doc.save()

                all_documents.append(doc)

                # 6. 재처리 필요 여부 판단
                group_config_changed = doc_group.name in changed_groups
                if self.re_embed or needs_reprocessing or group_config_changed:
                    documents_to_process.append(doc)
                    if group_config_changed and not needs_reprocessing:
                        await self.queue.put(
                            PipelineMessage.info(
                                f"Reprocessing '{doc.name}' due to group config change"
                            )
                        )

            except Exception as e:
                await self.queue.put(
                    PipelineMessage.warning(
                        f"Failed to process {file_info.fileName}: {str(e)}")
                )
                continue

        # 7. 삭제된 파일 처리: DB에는 있지만 files에 없는 문서들 제거
        deleted_count = await self._cleanup_deleted_files(group_mapping, all_documents)

        return all_documents, documents_to_process, deleted_count

    async def _delete_document_chunks(self, doc) -> int:
        """
        VDB에서 문서의 청크를 삭제합니다.

        Args:
            doc: Document 객체

        Returns:
            int: 삭제된 청크 수
        """
        return self.vdb.delete_all_chunks_by_document_id(doc.id)

    async def _add_document_chunks_to_vdb(
        self,
        doc,
        vdb_documents: list[dict],
        vectors: list[list[float]]
    ) -> int:
        """
        VDB에 문서의 청크를 추가합니다.

        Args:
            doc: Document 객체
            vdb_documents: VDB에 저장할 문서 리스트
            vectors: 임베딩 벡터 리스트

        Returns:
            int: 저장된 청크 수
        """
        await asyncio.to_thread(
            self.vdb.add_documents,
            documents=vdb_documents,
            embeddings=vectors,
        )
        return len(vdb_documents)

    async def _cleanup_deleted_files(self, group_mapping: dict, current_documents: list) -> int:
        """
        DB에는 있지만 현재 files에 없는 문서들을 삭제합니다.

        Args:
            group_mapping: path -> DocumentGroup 매핑
            current_documents: 현재 처리 중인 문서들

        Returns:
            int: 삭제된 파일 수
        """
        # 현재 문서들의 file_path 집합 생성
        current_file_paths = {doc.file_path for doc in current_documents}

        # 모든 그룹에 속한 문서들 조회
        deleted_count = 0
        for group_path, group in group_mapping.items():
            # 해당 그룹의 모든 문서 조회
            memberships = await DocumentGroupMembership.filter(group=group).prefetch_related("document")

            for membership in memberships:
                doc = membership.document

                # 현재 files에 없는 문서 발견
                if doc.file_path not in current_file_paths:
                    try:
                        # VDB에서 청크 삭제
                        deleted_chunks = await self._delete_document_chunks(doc)

                        # DB에서 문서 삭제 (membership도 CASCADE로 자동 삭제됨)
                        await doc.delete()

                        deleted_count += 1
                        await self.queue.put(
                            PipelineMessage.info(
                                f"  🗑️  Deleted removed file: {doc.name} ({deleted_chunks} chunks)")
                        )
                    except Exception as e:
                        await self.queue.put(
                            PipelineMessage.warning(
                                f"Failed to delete {doc.name}: {str(e)}")
                        )

        if deleted_count > 0:
            await self.queue.put(
                PipelineMessage.info(
                    f"✓ Cleaned up {deleted_count} deleted file(s)")
            )

        return deleted_count

    # ========== 파싱, 청킹, 임베딩, VDB 저장 ==========

    async def _process_documents(self, documents_to_process: list) -> dict:
        """
        File-level processing: Parse → Chunk → Embed → Save to VDB → Update status

        Args:
            documents_to_process: List of Document objects to process

        Returns:
            dict: Failed documents {filename: error_message}
        """
        failed_documents = {}

        if not documents_to_process:
            await self.queue.put(
                PipelineMessage.info("✅ No files to process (all unchanged)")
            )
            return failed_documents

        await self.queue.put(
            PipelineMessage.info(
                f"🔄 Processing {len(documents_to_process)} file(s)...")
        )

        embedder = get_embedder()
        total_chunks_saved = 0
        processed_count = 0

        # Process each file
        for doc in documents_to_process:
            try:
                # 1. 기존 VDB 청크 삭제
                try:
                    deleted_count = await self._delete_document_chunks(doc)
                    if deleted_count > 0:
                        await self.queue.put(
                            PipelineMessage.info(
                                f"  🗑️  Deleted {deleted_count} old chunk(s) for {doc.name}")
                        )
                except Exception as e:
                    await self.queue.put(
                        PipelineMessage.warning(
                            f"Failed to delete chunks for {doc.name}: {str(e)}")
                    )

                # 2. Get file path: use temp_file_path if available (uploaded files), otherwise use db path
                temp_file_path = doc.metadata.get(
                    "temp_file_path") if doc.metadata else None
                if temp_file_path and Path(temp_file_path).exists():
                    file_path = Path(temp_file_path)
                else:
                    file_path = Path(doc.file_path)

                # 3. Get group info from document metadata
                hierarchical_group_name = doc.metadata.get(
                    "hierarchical_group_name", self.group_name)
                group_version_id = doc.metadata.get("group_version_id")

                # Get RAG config for the group
                group_config = self._get_group_rag_components(
                    hierarchical_group_name)
                loader_name = group_config.get("loader")
                chunker_name = group_config.get("chunker")
                embedding_model = group_config.get("embedding_model")

                # 4. Parse document
                parse_result = self.loader_manager.parse(
                    file_path, loader_name=loader_name)

                if not parse_result.content.strip():
                    await self.queue.put(
                        PipelineMessage.warning(
                            f"Empty content for {doc.name}")
                    )
                    continue

                # 5. 청킹
                chunker = self.chunker_manager.get_chunker_or_default(
                    chunker_name)
                chunk_inputs = chunker.chunk(parse_result.content)

                if not chunk_inputs:
                    await self.queue.put(
                        PipelineMessage.warning(f"No chunks for {doc.name}")
                    )
                    continue

                # 6. Embedding
                chunk_texts = [chunk.content for chunk in chunk_inputs]
                vectors = await asyncio.to_thread(
                    embedder.encode,
                    chunk_texts,
                    embedding_model,
                    show_progress=False
                )

                # 7. Save to VDB
                vdb_documents = []
                for idx, (chunk_input, vector) in enumerate(zip(chunk_inputs, vectors)):
                    chunk_id = make_chunk_uid(doc.id, idx, chunk_input.content)

                    vdb_documents.append({
                        "id": chunk_id,
                        "content": chunk_input.content,
                        "metadata": {
                            "content": chunk_input.content,
                            "document_id": doc.id,
                            "document_name": doc.name,
                            "file_path": doc.file_path or "",
                            "chunk_number": idx,
                            "group": hierarchical_group_name,
                            "version_id": group_version_id,
                            **(chunk_input.meta or {}),
                        },
                    })

                chunks_saved = await self._add_document_chunks_to_vdb(
                    doc,
                    vdb_documents,
                    vectors
                )

                total_chunks_saved += chunks_saved

                # 8. 문서 상태 업데이트
                await update_document_status(doc, DocumentStatus.ACTIVE)

                processed_count += 1
                await self.queue.put(
                    PipelineMessage.info(
                        f"  ✓ {doc.name}: {len(chunk_inputs)} chunks saved")
                )

            except Exception as e:
                # Handle failed document processing
                error_msg = str(e)
                failed_documents[doc.name] = error_msg
                await self.queue.put(
                    PipelineMessage.error(f"  ✗ {doc.name}: {error_msg}")
                )

                # Delete failed document from DB (don't keep unparseable documents)
                try:
                    await doc.delete()
                except Exception as delete_error:
                    await self.queue.put(
                        PipelineMessage.warning(
                            f"Failed to delete document {doc.name}: {str(delete_error)}")
                    )
                continue

        await self.queue.put(
            PipelineMessage.info(
                f"  ✅ Processed {processed_count} file(s), saved {total_chunks_saved} chunks to VDB",
                data={"processed": processed_count,
                      "total_chunks": total_chunks_saved}
            )
        )

        return failed_documents

    # ========== Helper Methods ==========


# class DryIngestPipeline(IngestPipeline):
#     """
#     IngestPipeline의 Dry-run 버전

#     실제 DB/VDB 변경 없이 시뮬레이션만 수행하여 결과를 미리 확인
#     """

#     def __init__(
#         self,
#         files: List[Path],
#         group_name: str,
#         manager_id: int,
#         base_path: Path
#     ):
#         super().__init__(
#             files,
#             group_name,
#             manager_id,
#             base_path
#         )

#     async def _sync_group_and_documents(self):
#         """
#         DocumentGroup 계층 동기화 및 문서 생성을 시뮬레이션

#         실제 DB 변경 없이 simulate_ 함수를 사용하여 어떤 변경이 일어날지 확인
#         """
#         from maru_lang.services.document import (
#             simulate_upsert_document_group,
#             simulate_upsert_document_from_file,
#         )

#         file_hierarchies = []
#         unique_groups = {}
#         parent_child_pairs = set()

#         await self.queue.put(PipelineMessage.info("🔍 [DRY-RUN] Simulating group hierarchy..."))

#         # 1. 모든 파일의 그룹 계층 정보 수집
#         for f in self.files:
#             hierarchy = self._get_group_hierarchy_for_file(f.relativePath)
#             file_hierarchies.append((f, hierarchy))

#         # 2. 고유한 그룹들과 부모-자식 관계 추출
#         for _, hierarchy in file_hierarchies:
#             for parent_path, name, current_path in hierarchy:
#                 unique_groups[current_path] = name
#                 if parent_path:
#                     parent_child_pairs.add((parent_path, current_path))

#         # 3. 그룹 시뮬레이션
#         group_simulation_results = {}
#         for path, name in unique_groups.items():
#             rag_components = self._get_group_rag_components(name)

#             # 기존 그룹이 있고 manager가 다른 경우 권한 확인
#             from maru_lang.core.relation_db.models.documents import DocumentGroup
#             existing_group = await DocumentGroup.get_or_none(base_path=path)
#             if existing_group and existing_group.manager_id != self.manager_id:
#                 raise PermissionError(
#                     f"Access denied: User {self.manager_id} does not have permission to update DocumentGroup '{name}' "
#                     f"(managed by user {existing_group.manager_id})"
#                 )

#             if not existing_group or self.re_embed:
#                 force_new_version = True
#             elif existing_group.rag_components != rag_components:
#                 force_new_version = True
#             else:
#                 force_new_version = False

#             is_root_group = (name == self.group_name)
#             group_description = self.description if is_root_group else None

#             result = await simulate_upsert_document_group(
#                 name=name,
#                 base_path=path,
#                 manager_id=self.manager_id,
#                 rag_components=rag_components,
#                 force_new_version=force_new_version,
#                 description=group_description,
#             )
#             group_simulation_results[path] = result

#             await self.queue.put(
#                 PipelineMessage.info(
#                     f"  Group '{name}': {result['action']} - {result['reason']}")
#             )

#         # 4. Document 시뮬레이션
#         self.documents = []
#         self.documents_to_process = []

#         for file_path, hierarchy in file_hierarchies:
#             try:
#                 stat = file_path.stat()
#                 db_file_path = str(file_path.absolute())

#                 result = await simulate_upsert_document_from_file(
#                     name=file_path.stem,
#                     path=db_file_path,
#                     size=stat.st_size,
#                     mtime_ns=stat.st_mtime_ns,
#                     metadata={"original_filename": file_path.name},
#                 )

#                 # 시뮬레이션 결과만 저장 (실제 Document 객체는 없음)
#                 if result['needs_reprocessing']:
#                     self.documents_to_process.append({
#                         "file_path": file_path,
#                         "action": result['action'],
#                         "reason": result['reason']
#                     })

#                 self.documents.append({
#                     "file_path": file_path,
#                     "action": result['action'],
#                     "reason": result['reason'],
#                     "needs_reprocessing": result['needs_reprocessing']
#                 })

#                 if result['action'] != 'skip':
#                     await self.queue.put(
#                         PipelineMessage.info(
#                             f"  File '{file_path.name}': {result['action']} - {result['reason']}")
#                     )

#             except Exception as e:
#                 self.failed_documents[str(file_path)] = str(e)
#                 await self.queue.put(
#                     PipelineMessage.error(
#                         f"  File '{file_path.name}': Failed - {str(e)}")
#                 )

#         await self.queue.put(
#             PipelineMessage.info(
#                 f"✓ [DRY-RUN] Simulation complete: "
#                 f"{len(self.documents_to_process)} to process, "
#                 f"{len(self.documents) - len(self.documents_to_process)} to skip"
#             )
#         )

#     async def _process_documents(self):
#         """
#         문서 처리를 시뮬레이션 (실제 파싱/임베딩/VDB 저장 없음)
#         """
#         await self.queue.put(
#             PipelineMessage.info(
#                 f"🔍 [DRY-RUN] Would process {len(self.documents_to_process)} documents "
#                 f"(skipping actual parsing/embedding)"
#             )
#         )

#         # 실제 처리는 하지 않고, 지원되는 파일 타입만 체크
#         for doc_info in self.documents_to_process:
#             file_path = doc_info['file_path']

#             # 파일 타입 지원 여부 체크
#             if not self.loader_manager.supports(file_path):
#                 self.failed_documents[str(
#                     file_path)] = f"Unsupported file type: {file_path.suffix}"
#                 await self.queue.put(
#                     PipelineMessage.warning(
#                         f"  Would skip '{file_path.name}': Unsupported file type")
#                 )

#         await self.queue.put(
#             PipelineMessage.info(f"✓ [DRY-RUN] Processing simulation complete")
#         )

#     def _get_result(self) -> IngestResult:
#         """Dry-run 결과 반환 (실제 Document 객체 없음)"""
#         return IngestResult(
#             group=None,  # Dry-run에서는 그룹 미생성
#             documents=self.documents,  # dict 객체들
#             total_files=len(self.files) if self.files else 0,
#             processed_files=len(
#                 self.documents_to_process) if self.documents_to_process else 0,
#             skipped_files=(
#                 len(self.documents) - len(self.documents_to_process)
#                 if self.documents and self.documents_to_process
#                 else 0
#             ),
#             failed_files=len(self.failed_documents),
#             failed_details=self.failed_documents if self.failed_documents else None,
#         )
