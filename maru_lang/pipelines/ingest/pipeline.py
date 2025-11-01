"""
Ingest Pipeline - 로컬 파일 시스템을 ingest하는 파이프라인
"""
import re
from pathlib import Path
from typing import List, Optional, Tuple, Union
from dataclasses import dataclass
from maru_lang.pipelines.base import BasePipeline, PipelineMessage, PipelineComplete
from maru_lang.core.relation_db.models.documents import (
    Document,
    DocumentGroup,
    DocumentGroupMembership,
    DocumentGroupInclusion,
)
from maru_lang.enums.documents import DocumentStatus
from maru_lang.services.document import (
    upsert_document_group,
    set_document_group_inclusion,
    get_all_descendant_group_ids,
)
from maru_lang.core.vector_db.factory import get_vector_db, VectorDB
from maru_lang.configs.system_config import get_system_config
from maru_lang.pluggable.loaders import get_loader
from maru_lang.pluggable.chunkers import get_chunker
from maru_lang.configs import get_config_manager
from maru_lang.pluggable.embedders import get_embedder, Embedder
from maru_lang.models.vector_db import BaseVectorDBConfig
from maru_lang.utils.document import new_ulid, make_source_fingerprint_for_file
from tortoise.transactions import in_transaction

config = get_system_config()


@dataclass
class IngestResult:
    """Ingest 파이프라인 실행 결과"""

    group: DocumentGroup
    documents: List[Document]
    total_files: int
    processed_files: int
    skipped_files: int


class IngestPipeline(BasePipeline):
    """로컬 파일 시스템 ingest 파이프라인"""

    def __init__(
        self,
        path: Path,
        group_name: str,
        vdb_config: BaseVectorDBConfig,
        manager_id: int,
        max_batch_size_mb: int = 1000,
        re_embed: bool = False,
        verbose: bool = False,
    ):
        """
        Args:
            path: ingest할 디렉토리 경로
            group_name: 최상위 DocumentGroup 이름
            vdb_config: VectorDB 설정 (ChromaDB, Milvus 등)
            manager_id: 관리자 User ID
            max_batch_size_mb: 배치당 최대 메모리 크기 (MB, 기본: 1000MB)
            re_embed: 기존 임베딩을 삭제하고 처음부터 다시 임베딩할지 여부
            verbose: 자세한 출력 모드 (모든 처리되는 문서 표시)
        """
        super().__init__()
        self.path = path
        self.group_name = group_name
        self.vdb_config = vdb_config
        self.manager_id = manager_id
        self.max_batch_size_mb = max_batch_size_mb
        self.re_embed = re_embed
        self.verbose = verbose
        # MB를 chars로 변환 (대략 1 char = 1 byte 가정)
        self.max_chars_per_batch = max_batch_size_mb * 1024 * 1024

        # Config-driven 컴포넌트 로드
        config_manager = get_config_manager()

        self.loader_manager = get_loader()
        self.chunker_manager = get_chunker()

        # RAG config 로드 (그룹별 설정 조회용)
        # ConfigManager는 lazy loading이므로 명시적으로 로드 필요
        config_manager.ensure_loaded()
        self.rag_config = config_manager.get_rag_config()

        # Embedding model 설정 저장
        self.embedder_config = config_manager.get_embedder_config()
        if not self.embedder_config or not self.embedder_config.default_model:
            raise ValueError(
                "No embedding model configured. Please set default_model in embedder_config.yaml"
            )
        self.default_embedding_model = self.embedder_config.default_model

        # 중간 결과 저장
        self.all_files = []
        self.supported_files = []
        self.file_hierarchies = []
        self.group_cache = {}
        self.changed_groups = set()  # 설정이 변경된 그룹들
        self.documents_to_process = []  # 재처리 필요한 문서만
        self.doc_to_group = {}  # document_id -> group_name 매핑

        # VectorDB 인스턴스 (CRUD 직접 사용)
        self.vdb = None

        # 결과 저장
        self.files = None
        self.group = None
        self.unique_groups = None
        self.documents = None

    # ========== Pipeline Process ==========

    async def process(self):
        """파이프라인 주요 로직"""
        try:
            # 1. 입력 검증
            await self._validate_inputs()

            # 2. 파일 스캔
            await self._scan_files()
            # 3. 그룹 동기화 및 설정 변경 감지
            await self._sync_groups()

            # 4. VDB 설정
            await self._setup_vdb()

            # 5. Document 동기화
            await self._sync_documents()

            # 6. 파싱, 청킹, 임베딩, VDB 저장
            await self._process_documents()

            # 7. Document 상태 업데이트
            await self._update_document_status()

            # 8. 완료
            result = self._get_result()
            await self.queue.put(PipelineComplete(data=result))

        except Exception as e:
            await self.queue.put(PipelineMessage.error(f"Pipeline failed: {str(e)}"))
            await self.queue.put(PipelineComplete(data=None))
            raise

    # ========== Helper Methods ==========

    def _get_embedding_model_for_group(self, group_name: str) -> str:
        """
        그룹별 embedding model 결정

        Args:
            group_name: 그룹 이름

        Returns:
            embedding model 이름 (그룹 설정이 있으면 그것 사용, 없으면 default)
        """
        if self.rag_config:
            group_config = self.rag_config.groups.get(group_name)
            if group_config and group_config.components and group_config.components.embedder:
                return group_config.components.embedder

        return self.default_embedding_model

    async def _print_group_components(self):
        """그룹별 RAG 컴포넌트 설정 출력"""
        if not self.rag_config or not self.rag_config.groups:
            await self.queue.put(
                PipelineMessage.info("📦 RAG Components: Using default settings for all groups")
            )
            return

        await self.queue.put(PipelineMessage.info("📦 RAG Components Configuration:"))

        # 생성된 그룹 이름들 추출
        created_group_names = set(self.unique_groups.values())

        for group_name in sorted(created_group_names):
            group_config = self.rag_config.groups.get(group_name)

            if group_config and group_config.components:
                components = group_config.components
                parts = []

                if components.loader:
                    parts.append(f"loader={components.loader}")
                if components.chunker:
                    parts.append(f"chunker={components.chunker}")
                if components.embedder:
                    parts.append(f"embedder={components.embedder}")

                if parts:
                    await self.queue.put(
                        PipelineMessage.info(f"   {group_name}: {', '.join(parts)}")
                    )
                else:
                    await self.queue.put(
                        PipelineMessage.info(f"   {group_name}: using default components")
                    )
            else:
                await self.queue.put(
                    PipelineMessage.info(f"   {group_name}: using default components")
                )

    # ========== 입력 검증 ==========

    async def _validate_inputs(self):
        """입력값 검증 + 경로 충돌 검사"""
        await self.queue.put(PipelineMessage.info("🔍 Validating inputs..."))

        if not self.path.exists():
            await self.queue.put(
                PipelineMessage.error(f"Directory does not exist: {self.path}")
            )
            raise ValueError(f"Directory does not exist: {self.path}")

        if not self.path.is_dir():
            await self.queue.put(
                PipelineMessage.error(f"Path is not a directory: {self.path}")
            )
            raise ValueError(f"Path is not a directory: {self.path}")

        await self.queue.put(PipelineMessage.info(f"✓ Directory validated: {self.path}"))

    # ========== 파일 스캔 ==========

    async def _scan_files(self):
        """파일 스캔"""
        await self.queue.put(PipelineMessage.info("📂 Scanning files..."))

        self.all_files = sorted([f for f in self.path.rglob("*") if f.is_file()])
        await self.queue.put(
            PipelineMessage.info(f"Found {len(self.all_files)} total files")
        )

        self.supported_files = [
            f for f in self.all_files if self.loader_manager.supports(f)
        ]
        await self.queue.put(
            PipelineMessage.info(f"Found {len(self.supported_files)} supported files")
        )

        if not self.supported_files:
            await self.queue.put(
                PipelineMessage.error(f"No supported files found in: {self.path}")
            )
            raise ValueError(f"No supported files found in: {self.path}")

        self.files = self.supported_files
        await self.queue.put(PipelineMessage.info(f"✓ File scan completed"))

    # ========== DocumentGroup 계층 동기화 ==========

    async def _sync_groups(self):
        """
        DocumentGroup 계층 동기화 및 설정 변경 감지

        - 파일 시스템 구조에 맞춰 그룹 생성/업데이트
        - 그룹별 RAG 설정 저장 (loader, chunker, embedding_model)
        - 설정 변경 시 해당 그룹의 모든 문서를 재처리 대상으로 표시
        """
        await self.queue.put(PipelineMessage.info("🏗️  Syncing group hierarchy..."))

        # 1. 모든 파일의 그룹 계층 정보 수집
        for f in self.files:
            hierarchy = self._get_group_hierarchy_for_file(f)
            self.file_hierarchies.append((f, hierarchy))

        # 2. 고유한 그룹들과 부모-자식 관계 추출
        unique_groups = {}  # path -> name
        parent_child_pairs = set()

        for _, hierarchy in self.file_hierarchies:
            for parent_path, name, current_path in hierarchy:
                unique_groups[current_path] = name
                if parent_path:
                    parent_child_pairs.add((parent_path, current_path))

        await self.queue.put(
            PipelineMessage.info(f"Creating {len(unique_groups)} document group(s)...")
        )

        # 3. 그룹 생성 및 설정 변경 감지
        for path, name in unique_groups.items():
            # 그룹별 RAG config 조회
            loader_name = None
            chunker_name = None
            embedding_model = self._get_embedding_model_for_group(name)

            if self.rag_config:
                group_config = self.rag_config.groups.get(name)
                if group_config and group_config.components:
                    loader_name = group_config.components.loader
                    chunker_name = group_config.components.chunker

            # 현재 설정 스냅샷 생성
            config_snapshot = {
                "loader": loader_name,
                "chunker": chunker_name,
                "embedding_model": embedding_model,
            }

            # 기존 그룹 조회 (변경 감지용)
            existing_group = await DocumentGroup.get_or_none(base_path=path)

            if existing_group and existing_group.config_snapshot:
                # 설정 변경 감지
                old_snapshot = existing_group.config_snapshot
                if old_snapshot != config_snapshot:
                    self.changed_groups.add(name)
                    await self.queue.put(
                        PipelineMessage.info(
                            f"⚠️  Config changed for group '{name}': "
                            f"{old_snapshot} → {config_snapshot}"
                        )
                    )

            # 그룹 upsert
            group = await upsert_document_group(
                name=name,
                base_path=path,
                embedding_model=embedding_model,
                manager_id=self.manager_id,
                loader=loader_name,
                chunker=chunker_name,
                config_snapshot=config_snapshot,
            )
            self.group_cache[path] = group

            # Re-embed 모드: 해당 그룹의 기존 임베딩 삭제
            if self.re_embed:
                group_documents = (
                    await Document.filter(group_memberships__group_id=group.id)
                    .distinct()
                    .all()
                )

                if group_documents:
                    await self.queue.put(
                        PipelineMessage.info(
                            f"🔄 Re-embed: Deleting {len(group_documents)} document(s) embeddings from group '{name}'..."
                        )
                    )

                    vdb = get_vector_db(self.vdb_config)
                    total_deleted = 0
                    for doc in group_documents:
                        deleted_count = vdb.delete_all_chunks_by_document_id(doc.id)
                        total_deleted += deleted_count

                    await self.queue.put(
                        PipelineMessage.info(
                            f"   ✓ Deleted {total_deleted} chunk(s) from VectorDB"
                        )
                    )

        # 4. 부모-자식 관계 설정
        await self.queue.put(
            PipelineMessage.info(f"Setting up {len(parent_child_pairs)} group relationship(s)...")
        )

        for parent_path, child_path in parent_child_pairs:
            await set_document_group_inclusion(
                self.group_cache[parent_path], self.group_cache[child_path]
            )

        base_path_str = str(self.path.absolute())
        self.group = self.group_cache[base_path_str]
        self.unique_groups = unique_groups

        await self.queue.put(PipelineMessage.info("✓ Group hierarchy synced"))

        # 5. 설정 변경 요약
        if self.changed_groups:
            await self.queue.put(
                PipelineMessage.info(
                    f"📋 Config changed for {len(self.changed_groups)} group(s): "
                    f"{', '.join(sorted(self.changed_groups))}"
                )
            )

        # 6. 그룹별 RAG 컴포넌트 설정 출력
        await self._print_group_components()

    def _get_group_hierarchy_for_file(
        self, file_path: Path
    ) -> List[tuple[Optional[str], str, str]]:
        """
        파일의 그룹 계층 구조를 결정

        Returns:
            List of (parent_path, name, current_path) tuples
            - parent_path: 부모 그룹의 base_path (None이면 최상위)
            - name: 현재 그룹 이름 (디렉토리명)
            - current_path: 현재 그룹의 base_path
        """
        relative_path = file_path.relative_to(self.path)
        parts = relative_path.parts[:-1]  # 파일명 제외

        base_path_str = str(self.path.absolute())

        # 최상위 그룹 (base)
        if not parts:
            return [(None, self.group_name, base_path_str)]

        hierarchy = [(None, self.group_name, base_path_str)]

        # 하위 그룹들
        for i, part in enumerate(parts):
            # 현재 디렉토리의 실제 경로
            current_path = self.path / Path(*parts[: i + 1])
            current_path_str = str(current_path.absolute())

            # 부모 경로
            if i == 0:
                parent_path_str = base_path_str
            else:
                parent_path = self.path / Path(*parts[:i])
                parent_path_str = str(parent_path.absolute())

            # 이름은 디렉토리명만
            name = part

            hierarchy.append((parent_path_str, name, current_path_str))

        return hierarchy

    # ========== VectorDB 설정 ==========

    async def _setup_vdb(self):
        """VectorDB 인스턴스 생성 (CRUD 직접 사용)"""
        await self.queue.put(PipelineMessage.info("💾 Setting up vector database..."))

        # VectorDB 팩토리로 인스턴스 생성
        self.vdb = get_vector_db(self.vdb_config)

        # 헬스체크 수행
        try:
            self.vdb.health_check()
            await self.queue.put(
                PipelineMessage.info(
                    f"✓ VDB connected (default embedder: {self.default_embedding_model})"
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

        await self.queue.put(PipelineMessage.info(f"✓ VDB setup completed"))

    # ========== Document 생성 ==========

    async def _cleanup_deleted_files(self, current_documents: List[Document]):
        """
        파일 시스템에서 삭제된 파일을 RDB와 VDB에서 정리

        Args:
            current_documents: 현재 파일 시스템에 존재하는 문서 리스트
        """

        # 1. 이 그룹과 모든 하위 그룹의 ID 가져오기
        all_group_ids = await get_all_descendant_group_ids([self.group.id], inclusion_model=DocumentGroupInclusion)
        all_group_ids.add(self.group.id)

        # 2. RDB에서 이 그룹 계층의 모든 문서 가져오기
        rdb_documents = await Document.filter(
            group_memberships__group_id__in=list(all_group_ids)
        ).distinct().all()

        await self.queue.put(
            PipelineMessage.info(f"📊 RDB documents: {len(rdb_documents)}, Current documents: {len(current_documents)}")
        )

        # 3. 현재 파일 시스템에 있는 문서 ID
        current_doc_ids = {doc.id for doc in current_documents}

        # 4. 삭제된 문서 찾기
        deleted_documents = [doc for doc in rdb_documents if doc.id not in current_doc_ids]

        await self.queue.put(
            PipelineMessage.info(f"🔍 Checking deleted files: {len(deleted_documents)} candidates")
        )

        if not deleted_documents:
            await self.queue.put(PipelineMessage.info("✓ No deleted files found"))
            return

        await self.queue.put(
            PipelineMessage.info(
                f"🗑️  Found {len(deleted_documents)} deleted file(s), cleaning up..."
            )
        )

        total_chunks_deleted = 0

        for doc in deleted_documents:
            # 파일이 정말 삭제되었는지 재확인
            if not Path(doc.file_path).exists():
                try:
                    # VDB에서 청크 삭제
                    try:
                        chunks_deleted = self.vdb.delete_all_chunks_by_document_id(doc.id)
                        total_chunks_deleted += chunks_deleted
                    except Exception as e:
                        await self.queue.put(
                            PipelineMessage.warning(
                                f"Failed to delete VDB chunks for '{doc.name}': {str(e)}"
                            )
                        )

                    # RDB에서 문서 삭제 (DocumentGroupMembership도 CASCADE로 삭제됨)
                    await doc.delete()

                    await self.queue.put(
                        PipelineMessage.info(f"Deleted: {doc.name}")
                    )

                except Exception as e:
                    await self.queue.put(
                        PipelineMessage.warning(f"Failed to delete '{doc.name}': {str(e)}")
                    )

        if total_chunks_deleted > 0:
            await self.queue.put(
                PipelineMessage.info(
                    f"✓ Cleaned up {len(deleted_documents)} document(s) and {total_chunks_deleted} chunk(s)"
                )
            )

    async def _sync_documents(self):
        """Document 생성 및 그룹 연결 (변경 감지)"""
        await self.queue.put(PipelineMessage.info("📄 Creating documents..."))

        all_documents = []
        documents_to_process = []

        for file_path, hierarchy in self.file_hierarchies:
            try:
                # 1. Document 생성 및 변경 감지
                stat = file_path.stat()
                doc, needs_reprocessing = await self.upsert_document_from_file(
                    name=file_path.stem,
                    path=str(file_path),
                    size=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                    metadata={"original_filename": file_path.name},
                )

                # 2. 파일의 최종 그룹 결정
                # hierarchy[-1] = (parent_path, name, current_path)
                final_group_path = hierarchy[-1][2]

                # 3. DocumentGroup 연결
                doc_group = self.group_cache[final_group_path]
                await DocumentGroupMembership.get_or_create(
                    document=doc, group=doc_group
                )

                # 4. Document → Group 매핑 저장 (VectorDB metadata용)
                self.doc_to_group[doc.id] = doc_group.name

                all_documents.append(doc)

                # 4. 재처리 필요 여부 판단
                # - re_embed 모드인 경우 (모든 문서 재처리)
                # - 파일이 변경된 경우 (needs_reprocessing)
                # - 그룹 설정이 변경된 경우 (changed_groups에 포함)
                group_config_changed = doc_group.name in self.changed_groups
                if self.re_embed or needs_reprocessing or group_config_changed:
                    documents_to_process.append(doc)
                    if self.re_embed and not needs_reprocessing and not group_config_changed:
                        # re_embed 모드로 재처리되는 경우 (파일/설정 변경 없음)
                        if self.verbose:
                            await self.queue.put(
                                PipelineMessage.info(
                                    f"Re-embedding '{doc.name}' (forced by --re-embed)"
                                )
                            )
                    elif group_config_changed and not needs_reprocessing:
                        # 파일은 변경 안 됐지만 그룹 설정만 변경된 경우
                        await self.queue.put(
                            PipelineMessage.info(
                                f"Reprocessing '{doc.name}' due to group config change"
                            )
                        )

            except Exception as e:
                # 개별 파일 처리 실패는 로깅만 하고 계속 진행
                await self.queue.put(
                    PipelineMessage.warning(f"Failed to process {file_path.name}: {str(e)}")
                )
                continue

        self.documents = all_documents
        self.documents_to_process = documents_to_process

        # 삭제된 파일 감지 및 정리
        await self._cleanup_deleted_files(all_documents)

        # VDB-RDB 동기화 검증
        await self.queue.put(PipelineMessage.info("🔍 Verifying VDB-RDB synchronization..."))
        sync_stats = await self.verify_vdb_rdb_sync(self.group, self.documents_to_process, self.vdb)

        # 동기화 검증 결과 출력
        if sync_stats["missing_in_vdb"] > 0:
            await self.queue.put(
                PipelineMessage.warning(
                    f"⚠️  Found {sync_stats['missing_in_vdb']} document(s) in RDB without VDB chunks (will reprocess)"
                )
            )

        if sync_stats["orphan_chunks_deleted"] > 0:
            await self.queue.put(
                PipelineMessage.info(
                    f"🗑️  Cleaned up {sync_stats['orphan_chunks_deleted']} orphan chunk(s) from VDB"
                )
            )

        if sync_stats["missing_in_vdb"] == 0 and sync_stats["orphan_in_vdb"] == 0:
            await self.queue.put(PipelineMessage.info("✓ VDB-RDB sync verified"))

        # 재처리 통계 전달 (동기화 검증 후 업데이트된 documents_to_process 반영)
        await self.queue.put(
            PipelineMessage.info(
                f"📊 Document Status: Total={len(all_documents)}, "
                f"To Process={len(self.documents_to_process)}, "
                f"Skipped={len(all_documents) - len(self.documents_to_process)}",
                data={
                    "total": len(all_documents),
                    "to_process": len(self.documents_to_process),
                    "skipped": len(all_documents) - len(self.documents_to_process),
                }
            )
        )

    # ========== 파싱, 청킹, 임베딩, VDB 저장 (스트리밍) ==========

    async def _process_documents(self):
        """파싱 → 청킹 → 임베딩 → VDB 저장 (스트리밍으로 메모리 효율적)"""

        if not self.documents_to_process:
            await self.queue.put(
                PipelineMessage.info("✅ No files to process (all unchanged)")
            )
            return

        # 1. 기존 VDB 청크 삭제
        await self.queue.put(
            PipelineMessage.info(
                f"🗑️  Deleting old chunks for {len(self.documents_to_process)} document(s)..."
            )
        )

        for doc in self.documents_to_process:
            try:
                deleted_count = self.vdb.delete_all_chunks_by_document_id(doc.id)
                if deleted_count > 0:
                    await self.queue.put(
                        PipelineMessage.info(f"Deleted {deleted_count} chunk(s) for '{doc.name}'")
                    )
            except Exception as e:
                await self.queue.put(
                    PipelineMessage.warning(f"Failed to delete chunks for {doc.name}: {str(e)}")
                )

        # 2. 문서를 그룹별로 정리
        docs_by_group = {}
        for doc in self.documents_to_process:
            group_name = self.doc_to_group.get(doc.id, self.group_name)
            if group_name not in docs_by_group:
                docs_by_group[group_name] = []
            docs_by_group[group_name].append(doc)

        # 3. 스트리밍 처리 (파싱 → 청킹 → 임베딩 → VDB 저장)
        await self.queue.put(
            PipelineMessage.info(f"🔄 Processing {len(self.documents_to_process)} file(s) across {len(docs_by_group)} group(s)...")
        )

        embedder = get_embedder()
        batch_texts = []
        batch_metadata = []  # (doc, chunk_input, idx) 저장
        batch_docs = []  # 현재 배치에 포함된 문서 이름들
        current_batch_chars = 0
        total_chunks_saved = 0
        processed_docs = 0
        batch_number = 0
        current_group = None  # 현재 처리 중인 그룹 추적

        # 그룹별로 순회하면서 처리
        for group_name in sorted(docs_by_group.keys()):
            docs_in_group = docs_by_group[group_name]

            # 그룹 헤더 출력
            await self.queue.put(
                PipelineMessage.info(f"\n📁 Group: [{group_name}] ({len(docs_in_group)} file(s))")
            )

            # 그룹별 RAG config 조회 및 출력
            group_config = None
            if self.rag_config:
                group_config = self.rag_config.groups.get(group_name)

            loader_info = "auto"
            chunker_info = "default"
            if group_config and group_config.components:
                if group_config.components.loader:
                    loader_info = group_config.components.loader
                if group_config.components.chunker:
                    chunker_info = group_config.components.chunker

            await self.queue.put(
                PipelineMessage.info(f"   Loader: {loader_info}, Chunker: {chunker_info}")
            )

            for doc in docs_in_group:
                try:
                    # file_path를 Path 객체로 변환
                    file_path = Path(doc.file_path)

                    # 파싱: 그룹별 loader 설정 적용
                    loader_name = None
                    loader_source = "auto (extension)"  # 출력용
                    if group_config and group_config.components:
                        loader_name = group_config.components.loader

                    if loader_name:
                        # 그룹별 지정된 loader 사용
                        parse_result = self.loader_manager.parse(file_path, loader_name=loader_name)
                        loader_source = f"group config ({loader_name})"
                    else:
                        # 기본 loader 사용 (확장자 기반)
                        parse_result = self.loader_manager.parse(file_path)
                        # 실제 사용된 loader 이름 추출
                        loader = self.loader_manager.get_loader(file_path)
                        if loader:
                            loader_source = f"auto ({loader.__class__.__name__})"

                    if not parse_result.content.strip():
                        await self.queue.put(
                            PipelineMessage.warning(f"Empty content for {doc.name}")
                        )
                        continue

                    # 청킹: 그룹별 chunker 설정 적용
                    chunker_name = None
                    chunker_source = "default"  # 출력용
                    if group_config and group_config.components:
                        chunker_name = group_config.components.chunker
                        if chunker_name:
                            chunker_source = f"group config ({chunker_name})"

                    if not chunker_name:
                        # 그룹별 설정이 없으면 loader가 제안하는 chunker 사용
                        chunker_name = self.loader_manager.get_chunker_name_for_file(file_path)
                        chunker_source = f"loader suggestion ({chunker_name})"

                    chunker = self.chunker_manager.get_chunker_or_default(chunker_name)
                    chunk_inputs = chunker.chunk(parse_result.content)

                    # 파일별 출력
                    if self.verbose:
                        # verbose 모드: 상세 정보
                        await self.queue.put(
                            PipelineMessage.info(
                                f"   ├─ {doc.name}\n"
                                f"   │  → Loader: {loader_source}\n"
                                f"   │  → Chunker: {chunker_source}\n"
                                f"   │  → Chunks: {len(chunk_inputs)}"
                            )
                        )
                    else:
                        # 일반 모드: 파일명과 청크 개수만
                        await self.queue.put(
                            PipelineMessage.info(
                                f"   ├─ {doc.name} ({len(chunk_inputs)} chunks)"
                            )
                        )

                    if not chunk_inputs:
                        await self.queue.put(
                            PipelineMessage.warning(f"No chunks for {doc.name}")
                        )
                        continue

                    # 청크를 배치에 추가
                    doc_added_to_batch = False
                    for idx, chunk_input in enumerate(chunk_inputs):
                        chunk_chars = len(chunk_input.content)

                        # 배치가 꽉 차면 임베딩 및 저장
                        if current_batch_chars + chunk_chars > self.max_chars_per_batch and batch_texts:
                            batch_number += 1
                            # 배치 임베딩
                            await self._process_and_save_batch(
                                batch_number, batch_texts, batch_metadata, batch_docs,
                                current_batch_chars, embedder
                            )
                            total_chunks_saved += len(batch_texts)

                            # 배치 초기화
                            batch_texts = []
                            batch_metadata = []
                            batch_docs = []
                            current_batch_chars = 0
                            doc_added_to_batch = False

                        # 현재 청크를 배치에 추가
                        batch_texts.append(chunk_input.content)
                        batch_metadata.append((doc, chunk_input, idx))
                        current_batch_chars += chunk_chars

                        # 문서 이름을 배치에 추가 (한 번만)
                        if not doc_added_to_batch:
                            batch_docs.append(doc.name)
                            doc_added_to_batch = True

                    processed_docs += 1

                except Exception as e:
                    await self.queue.put(
                        PipelineMessage.error(f"   ├─ Error: {doc.name} - {str(e)}")
                    )
                    continue

        # 남은 배치 처리
        if batch_texts:
            batch_number += 1
            await self._process_and_save_batch(
                batch_number, batch_texts, batch_metadata, batch_docs,
                current_batch_chars, embedder, is_final=True
            )
            total_chunks_saved += len(batch_texts)

        await self.queue.put(
            PipelineMessage.info(
                f"✅ Total {total_chunks_saved} chunks saved to VDB",
                data={"total_chunks": total_chunks_saved}
            )
        )

    async def _process_and_save_batch(
        self,
        batch_number: int,
        batch_texts: list,
        batch_metadata: list,
        batch_docs: list,
        current_batch_chars: int,
        embedder: Embedder,
        is_final: bool = False
    ):
        """
        배치 처리 및 저장 (임베딩 → VDB 저장)

        Args:
            batch_number: 배치 번호
            batch_texts: 배치에 포함된 텍스트 리스트
            batch_metadata: (doc, chunk_input, idx) 튜플 리스트
            batch_docs: 배치에 포함된 문서 이름 리스트
            current_batch_chars: 현재 배치의 문자 수
            embedder: 임베더 인스턴스
            is_final: 마지막 배치 여부
        """
        import hashlib

        # 문서 목록 포맷팅
        if self.verbose:
            docs_str = ", ".join(batch_docs)
        else:
            # verbose가 아닐 때는 처음 3개만 표시
            if len(batch_docs) <= 3:
                docs_str = ", ".join(batch_docs)
            else:
                docs_str = ", ".join(batch_docs[:3]) + f" 외 {len(batch_docs) - 3}개"

        prefix = "Embedding final batch" if is_final else f"Embedding batch #{batch_number}"
        await self.queue.put(
            PipelineMessage.info(
                f"{prefix}: {len(batch_texts)} chunks (~{current_batch_chars:,} chars)\n"
                f"   📄 Documents: {docs_str}"
            )
        )

        # 임베딩 (비동기로 실행하여 UI 블로킹 방지)
        import asyncio
        await self.queue.put(
            PipelineMessage.info(f"   ⏳ Generating embeddings...")
        )

        vectors = await asyncio.to_thread(
            embedder.encode,
            batch_texts,
            self.default_embedding_model,
            show_progress=False
        )

        await self.queue.put(
            PipelineMessage.info(f"   ✓ Embeddings generated, saving to VDB...")
        )

        # VDB 저장 준비
        vdb_documents = []
        for (doc, chunk_input, idx), vector in zip(batch_metadata, vectors):
            chunk_id = hashlib.blake2b(
                f"{doc.id}:{idx}".encode(), digest_size=8
            ).hexdigest()

            vdb_documents.append({
                "id": chunk_id,
                "content": chunk_input.content,
                "metadata": {
                    "content": chunk_input.content,
                    "document_id": doc.id,
                    "document_name": doc.name,
                    "file_path": doc.file_path or "",
                    "chunk_number": idx,
                    "group": self.doc_to_group.get(doc.id, self.group.name),  # 실제 그룹 이름 사용
                    **(chunk_input.meta or {}),
                },
            })

        # VectorDB에 문서와 임베딩 벡터 함께 저장 (비동기로 실행)
        await asyncio.to_thread(
            self.vdb.add_documents,
            documents=vdb_documents,
            embeddings=vectors,
        )

        await self.queue.put(
            PipelineMessage.info(f"   ✓ Batch #{batch_number} saved to VDB")
        )

    # ========== Helper Methods ==========

    async def upsert_document_from_file(
        self,
        name: str,
        path: str,
        size: int,
        mtime_ns: int,
        metadata: Optional[dict] = None,
    ) -> Tuple[Document, bool]:
        """
        파일 기반 문서 업서트

        파일 경로로 Document를 찾고, fingerprint로 변경 여부 확인
        변경된 경우 PROCESSING 상태로 되돌려 재처리 필요함을 표시

        Args:
            name: 문서 이름
            path: 파일 전체 경로
            size: 파일 크기 (bytes)
            mtime_ns: 수정 시간 (nanoseconds)
            metadata: 추가 메타데이터

        Returns:
            Tuple[Document, bool]: (문서, 재처리필요여부)
            - 재처리필요 = True: 신규 생성 또는 파일 수정됨
            - 재처리필요 = False: 기존 파일이고 변경 없음
        """
        filename = Path(path).name
        fp = make_source_fingerprint_for_file(filename, size, mtime_ns)

        async with in_transaction():
            # 1. 파일 경로로 기존 Document 조회
            doc = await Document.get_or_none(file_path=path)

            if doc:
                # 2. 기존 문서 존재 → fingerprint 비교
                if doc.source_fingerprint == fp:
                    # fingerprint 동일 = 파일 수정 없음 → 재처리 불필요
                    doc.name = name or doc.name
                    doc.metadata = {**(doc.metadata or {}), **(metadata or {})}
                    await doc.save()
                    return doc, False

                # fingerprint 다름 = 파일 수정됨 → 재처리 필요
                doc.name = name
                doc.file_size = size
                doc.source_fingerprint = fp
                doc.status = DocumentStatus.PROCESSING  # 재처리 위해 PROCESSING으로
                doc.metadata = {**(doc.metadata or {}), **(metadata or {})}
                await doc.save()
                return doc, True

            # 3. 신규 생성 (PROCESSING 상태)
            new_doc = await Document.create(
                id=new_ulid(),
                name=name,
                file_path=path,
                file_size=size,
                source_fingerprint=fp,
                status=DocumentStatus.PROCESSING,
                metadata=metadata or {},
            )
            return new_doc, True

    async def verify_vdb_rdb_sync(
        self, 
        group: DocumentGroup,
        documents_to_process: List[Document],
        vdb: VectorDB,
    ) -> dict:
        """
        VDB와 RDB 동기화 상태 검증 및 불일치 해결

        Args:
            group: 검증할 DocumentGroup
            documents_to_process: 재처리 대상 문서 리스트 (불일치 발견 시 추가됨)
            vdb: VectorDB 인스턴스 (CRUD 직접 사용)

        Returns:
            dict: 검증 결과 통계
                - missing_in_vdb: RDB에는 있지만 VDB에 없는 문서 수
                - orphan_in_vdb: VDB에는 있지만 RDB에 없는 문서 수
                - orphan_chunks_deleted: 삭제된 orphan 청크 수
        """
        stats = {
            "missing_in_vdb": 0,
            "orphan_in_vdb": 0,
            "orphan_chunks_deleted": 0,
        }

        # 1. RDB에서 이 그룹의 모든 문서 ID 가져오기
        rdb_documents = await Document.filter(
            group_memberships__group=group
        ).distinct().all()
        rdb_doc_ids = {doc.id for doc in rdb_documents}

        # 2. VDB에서 이 그룹의 모든 청크 document_id 가져오기 (그룹 필터 적용)
        try:
            # ChromaDB의 get_all_metadata는 where 파라미터를 받지 않으므로
            # collection.get()을 직접 사용
            result = vdb.collection.get(
                where={"group": group.name},
                include=["metadatas"]
            )
            all_metadata = result.get("metadatas", [])
            vdb_doc_ids = {meta.get("document_id") for meta in all_metadata if meta.get("document_id")}
        except Exception as e:
            # VDB 메타데이터 조회 실패 시 검증 스킵
            return stats

        # 3. 불일치 감지 및 처리
        # 케이스 1: RDB에는 있지만 VDB에는 없는 문서 (청크 누락)
        missing_in_vdb = rdb_doc_ids - vdb_doc_ids
        if missing_in_vdb:
            stats["missing_in_vdb"] = len(missing_in_vdb)
            missing_docs = [doc for doc in rdb_documents if doc.id in missing_in_vdb]

            # 재처리 대상에 추가
            for doc in missing_docs:
                if doc not in documents_to_process:
                    # 파일이 실제로 존재하는지 확인
                    if Path(doc.file_path).exists():
                        documents_to_process.append(doc)
                    else:
                        # 파일이 삭제된 경우 RDB에서도 삭제
                        await doc.delete()
                        stats["missing_in_vdb"] -= 1

        # 케이스 2: VDB에는 있지만 RDB에는 없는 문서 (orphan chunks)
        orphan_in_vdb = vdb_doc_ids - rdb_doc_ids
        if orphan_in_vdb:
            stats["orphan_in_vdb"] = len(orphan_in_vdb)

            # Orphan 청크 삭제
            for orphan_id in orphan_in_vdb:
                try:
                    count = vdb.delete_all_chunks_by_document_id(orphan_id)
                    stats["orphan_chunks_deleted"] += count
                except Exception:
                    # 삭제 실패는 무시하고 계속 진행
                    pass

        return stats

    async def _update_document_status(self):
        """재처리된 Document만 ACTIVE로 업데이트"""
        await self.queue.put(PipelineMessage.info("✅ Updating document status..."))

        if not self.documents_to_process:
            await self.queue.put(PipelineMessage.info("No documents to update"))
            return

        for doc in self.documents_to_process:
            doc.status = DocumentStatus.ACTIVE
            await doc.save()

        await self.queue.put(
            PipelineMessage.info(
                f"✅ Updated {len(self.documents_to_process)} document(s) to ACTIVE"
            )
        )

    def _get_result(self) -> IngestResult:
        """결과 반환 (헬퍼 메서드)"""
        return IngestResult(
            group=self.group,
            documents=self.documents,
            total_files=len(self.files) if self.files else 0,
            processed_files=len(self.documents_to_process) if self.documents_to_process else 0,
            skipped_files=(
                len(self.documents) - len(self.documents_to_process)
                if self.documents and self.documents_to_process
                else 0
            ),
        )
