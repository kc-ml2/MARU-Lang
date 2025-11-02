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
        virtual_path: Optional[Path] = None,
        all_files_list: Optional[list] = None,
    ):
        """
        Args:
            path: ingest할 디렉토리 경로 (실제 파일 작업용)
            group_name: 최상위 DocumentGroup 이름
            vdb_config: VectorDB 설정 (ChromaDB, Milvus 등)
            manager_id: 관리자 User ID
            max_batch_size_mb: 배치당 최대 메모리 크기 (MB, 기본: 1000MB)
            re_embed: 기존 임베딩을 삭제하고 처음부터 다시 임베딩할지 여부
            virtual_path: DB 저장용 가상 경로 (None이면 path 사용, API upload용)
            all_files_list: 전체 파일 목록 (배치 업로드 시 삭제 판단용, relativePath 배열)
        """
        super().__init__()
        self.path = path  # 실제 파일 작업용 (파싱, 스캔 등)
        self.virtual_path = virtual_path or path  # DB 저장용 (file_path, base_path 등)
        self.group_name = group_name
        self.vdb_config = vdb_config
        self.manager_id = manager_id
        self.max_batch_size_mb = max_batch_size_mb
        self.re_embed = re_embed
        self.all_files_list = all_files_list  # 전체 파일 목록 (배치 업로드용)
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
        self.doc_to_version_id = {}  # document_id -> version_id 매핑

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

    def _get_base_path_str(self) -> str:
        """
        Get base path string for DocumentGroup.
        Uses virtual_path for DB storage.
        """
        return str(self.virtual_path.absolute())

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
            if group_config and group_config.components and group_config.components.embedding_model:
                return group_config.components.embedding_model

        return self.default_embedding_model

    async def _print_group_components(self):
        """그룹별 RAG 컴포넌트 설정 출력"""
        if not self.rag_config or not self.rag_config.groups:
            # Default 설정일 경우 아무것도 출력하지 않음
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
                if components.embedding_model:
                    parts.append(f"embedding_model={components.embedding_model}")

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
        self.supported_files = [
            f for f in self.all_files if self.loader_manager.supports(f)
        ]

        if not self.supported_files:
            await self.queue.put(
                PipelineMessage.error(f"No supported files found in: {self.path}")
            )
            raise ValueError(f"No supported files found in: {self.path}")

        self.files = self.supported_files
        await self.queue.put(
            PipelineMessage.info(
                f"  ✓ Found {len(self.supported_files)} supported files ({len(self.all_files)} total)"
            )
        )

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

        # 3. 그룹 생성 및 설정 변경 감지
        created_count = 0
        updated_count = 0

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
            config_changed = False

            # 기존 그룹이 있고 manager가 다른 경우 권한 확인
            if existing_group and existing_group.manager_id != self.manager_id:
                raise PermissionError(
                    f"Access denied: User {self.manager_id} does not have permission to update DocumentGroup '{name}' "
                    f"(managed by user {existing_group.manager_id})"
                )

            if existing_group and existing_group.config_snapshot:
                # 설정 변경 감지
                old_snapshot = existing_group.config_snapshot
                if old_snapshot != config_snapshot:
                    config_changed = True
                    self.changed_groups.add(name)

                    # 변경된 항목만 추출
                    changes = []
                    for key in ['loader', 'chunker', 'embedding_model']:
                        old_val = old_snapshot.get(key)
                        new_val = config_snapshot.get(key)
                        if old_val != new_val:
                            old_str = old_val if old_val else 'default'
                            new_str = new_val if new_val else 'default'
                            changes.append(f"{key}: {old_str} → {new_str}")

                    if changes:
                        await self.queue.put(
                            PipelineMessage.info(
                                f"  ⚠️  Config changed for '{name}': {', '.join(changes)}"
                            )
                        )

            # 그룹 upsert (config 변경 또는 re-embed 시 새 version_id 생성)
            force_new_version = config_changed or self.re_embed
            group, created = await upsert_document_group(
                name=name,
                base_path=path,
                embedding_model=embedding_model,
                manager_id=self.manager_id,
                loader=loader_name,
                chunker=chunker_name,
                config_snapshot=config_snapshot,
                force_new_version=force_new_version,
            )
            self.group_cache[path] = group

            if created:
                created_count += 1
            else:
                updated_count += 1

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
        for parent_path, child_path in parent_child_pairs:
            await set_document_group_inclusion(
                self.group_cache[parent_path], self.group_cache[child_path]
            )

        base_path_str = self._get_base_path_str()
        self.group = self.group_cache[base_path_str]
        self.unique_groups = unique_groups

        # 요약 메시지
        summary_parts = []
        if created_count > 0:
            summary_parts.append(f"{created_count} created")
        if updated_count > 0:
            summary_parts.append(f"{updated_count} updated")
        if parent_child_pairs:
            summary_parts.append(f"{len(parent_child_pairs)} relationships")

        await self.queue.put(
            PipelineMessage.info(f"  ✓ Groups synced: {', '.join(summary_parts)}")
        )

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
            - name: 현재 그룹의 full path 이름 (unique 식별자)
            - current_path: 현재 그룹의 base_path
        """
        relative_path = file_path.relative_to(self.path)
        parts = relative_path.parts[:-1]  # 파일명 제외

        base_path_str = self._get_base_path_str()

        # 최상위 그룹 (base)
        if not parts:
            return [(None, self.group_name, base_path_str)]

        hierarchy = [(None, self.group_name, base_path_str)]

        # 하위 그룹들
        for i, part in enumerate(parts):
            # virtual_path 기준으로 경로 구성
            current_path = self.virtual_path / Path(*parts[: i + 1])
            current_path_str = str(current_path.absolute())

            # 부모 경로
            if i == 0:
                parent_path_str = base_path_str
            else:
                parent_path = self.virtual_path / Path(*parts[:i])
                parent_path_str = str(parent_path.absolute())

            # 이름은 full path (최상위 그룹명 + "/" + 하위 경로)
            # 예: "jihoon7/cinfact" + "/" + "docs/legal" = "jihoon7/cinfact/docs/legal"
            subpath = "/".join(parts[: i + 1])
            name = f"{self.group_name}/{subpath}"

            hierarchy.append((parent_path_str, name, current_path_str))

        return hierarchy

    # ========== VectorDB 설정 ==========

    async def _setup_vdb(self):
        """VectorDB 인스턴스 생성 (CRUD 직접 사용)"""
        # VectorDB 팩토리로 인스턴스 생성
        self.vdb = get_vector_db(self.vdb_config)

        # 헬스체크 수행
        try:
            self.vdb.health_check()
            await self.queue.put(
                PipelineMessage.info(
                    f"💾 VDB connected (embedder: {self.default_embedding_model})"
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

        # 3. 현재 파일 시스템에 있는 문서 ID 결정
        # 배치 업로드인 경우 all_files_list 사용, 아니면 current_documents 사용
        if self.all_files_list:
            # 배치 업로드: all_files_list로부터 전체 파일 경로 목록 생성
            # all_files_list는 relativePath 배열이므로 virtual_path와 결합
            # RDB에는 상대 경로로 저장되므로 절대 경로 변환하지 않음
            expected_file_paths = {
                str(self.virtual_path / file_path)
                for file_path in self.all_files_list
            }
            # RDB 문서 중 expected_file_paths에 있는 것만 "존재하는 파일"로 간주
            current_doc_ids = {
                doc.id for doc in rdb_documents
                if doc.file_path in expected_file_paths
            }
        else:
            # 일반 업로드: current_documents 기준
            current_doc_ids = {doc.id for doc in current_documents}

        # 4. 삭제된 문서 찾기
        deleted_documents = [doc for doc in rdb_documents if doc.id not in current_doc_ids]

        if not deleted_documents:
            return

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

                except Exception as e:
                    await self.queue.put(
                        PipelineMessage.warning(f"Failed to delete '{doc.name}': {str(e)}")
                    )

        # 요약만 출력
        await self.queue.put(
            PipelineMessage.info(
                f"  🗑️  Cleaned up: {len(deleted_documents)} deleted file(s), {total_chunks_deleted} chunk(s) removed"
            )
        )

    async def _sync_documents(self):
        """Document 생성 및 그룹 연결 (변경 감지)"""
        await self.queue.put(PipelineMessage.info("📄 Syncing documents..."))

        all_documents = []
        documents_to_process = []

        for file_path, hierarchy in self.file_hierarchies:
            try:
                # 1. Document 생성 및 변경 감지
                stat = file_path.stat()

                # DB 저장용 경로 계산
                if self.virtual_path != self.path:
                    # API upload: virtual_path 기준 상대 경로
                    relative_path = str(file_path.relative_to(self.path))
                    db_file_path = str(self.virtual_path / relative_path)
                else:
                    # CLI: 절대 경로 유지
                    db_file_path = str(file_path)

                doc, needs_reprocessing = await self.upsert_document_from_file(
                    name=file_path.stem,
                    path=db_file_path,  # DB 저장용 경로
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

                # 4. 계층 경로 생성 (VectorDB metadata용)
                # hierarchy에서 모든 그룹의 full path name을 추출하여 "_"로 연결
                # 예: ["jihoon7/cinfact", "jihoon7/cinfact/docs"] → "jihoon7/cinfact_jihoon7/cinfact/docs"
                group_path_parts = [h[1] for h in hierarchy]  # h[1] = name (full path)
                hierarchical_group_name = "_".join(group_path_parts)

                # 5. Document → Group 매핑 저장 (VectorDB metadata용)
                self.doc_to_group[doc.id] = hierarchical_group_name
                self.doc_to_version_id[doc.id] = doc_group.version_id

                all_documents.append(doc)

                # 4. 재처리 필요 여부 판단
                # - re_embed 모드인 경우 (모든 문서 재처리)
                # - 파일이 변경된 경우 (needs_reprocessing)
                # - 그룹 설정이 변경된 경우 (changed_groups에 포함)
                group_config_changed = doc_group.name in self.changed_groups
                if self.re_embed or needs_reprocessing or group_config_changed:
                    documents_to_process.append(doc)
                    if group_config_changed and not needs_reprocessing:
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
        sync_stats = await self.verify_vdb_rdb_sync(self.group, self.documents_to_process, self.vdb)

        # 동기화 검증 결과는 문제가 있을 때만 출력
        if sync_stats["wrong_version_chunks_deleted"] > 0:
            await self.queue.put(
                PipelineMessage.info(
                    f"  🗑️  Cleaned up {sync_stats['wrong_version_chunks_deleted']} wrong-version chunk(s) from VDB"
                )
            )

        if sync_stats["missing_in_vdb"] > 0:
            await self.queue.put(
                PipelineMessage.warning(
                    f"⚠️  Found {sync_stats['missing_in_vdb']} document(s) in RDB without VDB chunks (will reprocess)"
                )
            )

        if sync_stats["orphan_chunks_deleted"] > 0:
            await self.queue.put(
                PipelineMessage.info(
                    f"  🗑️  Cleaned up {sync_stats['orphan_chunks_deleted']} orphan chunk(s) from VDB"
                )
            )

        # 요약 출력
        to_process = len(self.documents_to_process)
        skipped = len(all_documents) - to_process
        summary_parts = [f"{len(all_documents)} total"]
        if to_process > 0:
            summary_parts.append(f"{to_process} to process")
        if skipped > 0:
            summary_parts.append(f"{skipped} skipped")

        await self.queue.put(
            PipelineMessage.info(
                f"  ✓ Documents synced: {', '.join(summary_parts)}",
                data={
                    "total": len(all_documents),
                    "to_process": to_process,
                    "skipped": skipped,
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
        total_deleted = 0
        for doc in self.documents_to_process:
            try:
                deleted_count = self.vdb.delete_all_chunks_by_document_id(doc.id)
                total_deleted += deleted_count
            except Exception as e:
                await self.queue.put(
                    PipelineMessage.warning(f"Failed to delete chunks for {doc.name}: {str(e)}")
                )

        if total_deleted > 0:
            await self.queue.put(
                PipelineMessage.info(
                    f"  🗑️  Deleted {total_deleted} old chunk(s) for {len(self.documents_to_process)} document(s)"
                )
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

            # 그룹별 RAG config 조회
            group_config = None
            if self.rag_config:
                group_config = self.rag_config.groups.get(group_name)

            for doc in docs_in_group:
                try:
                    # doc.file_path를 실제 파일 경로로 변환
                    if self.virtual_path != self.path:
                        # virtual_path 사용 시: virtual_path 제거 후 self.path와 결합
                        relative_path = Path(doc.file_path).relative_to(self.virtual_path)
                        file_path = self.path / relative_path
                    else:
                        # 기본: doc.file_path가 절대 경로
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
                f"  ✅ Saved {total_chunks_saved} chunks to VDB",
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

        # 임베딩 (비동기로 실행하여 UI 블로킹 방지)
        import asyncio

        vectors = await asyncio.to_thread(
            embedder.encode,
            batch_texts,
            self.default_embedding_model,
            show_progress=False
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
                    "version_id": self.doc_to_version_id.get(doc.id),  # DocumentGroup의 version_id
                    **(chunk_input.meta or {}),
                },
            })

        # VectorDB에 문서와 임베딩 벡터 함께 저장 (비동기로 실행)
        await asyncio.to_thread(
            self.vdb.add_documents,
            documents=vdb_documents,
            embeddings=vectors,
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
        fp = make_source_fingerprint_for_file(path, size, mtime_ns)

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
                - wrong_version_chunks_deleted: 잘못된 버전의 청크 수
        """
        stats = {
            "missing_in_vdb": 0,
            "orphan_in_vdb": 0,
            "orphan_chunks_deleted": 0,
            "wrong_version_chunks_deleted": 0,
        }

        # 1. RDB에서 이 그룹 및 모든 하위 그룹의 문서 ID 가져오기
        all_group_ids = await get_all_descendant_group_ids(
            [group.id],
            inclusion_model=DocumentGroupInclusion
        )
        rdb_documents = await Document.filter(
            group_memberships__group_id__in=all_group_ids
        ).distinct().all()
        rdb_doc_ids = {doc.id for doc in rdb_documents}

        # 2. VDB에서 이 그룹 계층의 모든 청크 메타데이터 가져오기
        # group.name은 unique하고 full path이므로 명확한 매칭 가능
        # 예: "jihoon7/cinfact" → "jihoon7/cinfact" 또는 "jihoon7/cinfact_jihoon7/cinfact/docs"
        try:
            # version_id로 필터링 (가장 정확함)
            if group.version_id:
                result = vdb.collection.get(
                    where={"version_id": group.version_id},
                    include=["metadatas", "ids"]
                )
            else:
                # version_id가 없으면 전체 조회 후 필터링
                result = vdb.collection.get(
                    include=["metadatas", "ids"]
                )

            all_metadata = result.get("metadatas", [])
            all_ids = result.get("ids", [])

            # 계층 경로가 이 그룹으로 시작하는 청크들만 필터링
            # group.name이 unique full path이므로 정확한 prefix 매칭
            # 예: group.name="jihoon7/cinfact"
            #     → "jihoon7/cinfact" (정확히 일치)
            #     → "jihoon7/cinfact_jihoon7/cinfact/docs" (하위 그룹)
            #     → "jihoon7/cinfact_jihoon7/cinfact/legal" (하위 그룹)
            vdb_doc_ids = set()
            for meta in all_metadata:
                if meta.get("document_id"):
                    chunk_group = meta.get("group", "")
                    # 계층 경로가 현재 그룹의 full path로 시작하면 포함
                    if chunk_group == group.name or chunk_group.startswith(f"{group.name}_"):
                        vdb_doc_ids.add(meta.get("document_id"))
        except Exception as e:
            # VDB 메타데이터 조회 실패 시 검증 스킵
            return stats

        # 2.5. 버전 불일치 청크 감지 및 삭제
        if group.version_id:
            wrong_version_ids = []
            for chunk_id, meta in zip(all_ids, all_metadata):
                chunk_version = meta.get("version_id")
                # version_id가 없거나 현재 그룹의 version_id와 다른 경우
                if chunk_version != group.version_id:
                    wrong_version_ids.append(chunk_id)

            if wrong_version_ids:
                try:
                    vdb.collection.delete(ids=wrong_version_ids)
                    stats["wrong_version_chunks_deleted"] = len(wrong_version_ids)
                    # 삭제된 청크의 document_id들을 재처리 대상에 추가
                    wrong_version_doc_ids = {
                        meta.get("document_id")
                        for chunk_id, meta in zip(all_ids, all_metadata)
                        if chunk_id in wrong_version_ids and meta.get("document_id") in rdb_doc_ids
                    }
                    for doc in rdb_documents:
                        if doc.id in wrong_version_doc_ids and doc not in documents_to_process:
                            documents_to_process.append(doc)
                except Exception:
                    pass

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
        if not self.documents_to_process:
            return

        for doc in self.documents_to_process:
            doc.status = DocumentStatus.ACTIVE
            await doc.save()

        await self.queue.put(
            PipelineMessage.info(
                f"  ✅ Updated {len(self.documents_to_process)} document(s) to ACTIVE"
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
