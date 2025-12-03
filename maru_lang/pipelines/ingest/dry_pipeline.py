"""
Dry-run Ingest Pipeline - Simulates processing without actual DB/VDB changes
"""
from pathlib import Path
from typing import List

from maru_lang.pipelines.base import PipelineMessage, PipelineComplete
from maru_lang.models.ingest import IngestResult
from maru_lang.pipelines.ingest.pipeline import IngestPipeline
from maru_lang.schemas.ingest import FileInfo
from maru_lang.services.document import simulate_upsert_document_group, simulate_upsert_document_from_file
from maru_lang.core.relation_db.models.documents import DocumentGroup, DocumentGroupMembership


class DryIngestPipeline(IngestPipeline):
    """
    Dry-run version of IngestPipeline

    Checks which files will be processed without actual DB/VDB changes
    """

    def __init__(
        self,
        files: List[FileInfo],
        group_name: str,
        manager_id: int,
        base_path: Path
    ):
        super().__init__(
            files,
            group_name,
            manager_id,
            base_path
        )

    async def process(self):
        """Dry-run: Check which files will be processed"""
        try:
            await self.queue.put(PipelineMessage.info("🔍 [DRY-RUN] Checking files..."))

            # 1. Collect group hierarchy information
            unique_groups, parent_child_pairs, file_hierarchies = await self._get_group_hierarchy()

            # 2. Simulate group operations and get group_mapping
            changed_groups, group_mapping = await self._simulate_groups(unique_groups)

            # 3. Simulate document operations
            total_files, files_to_process_indices, unsupported_file_indices, files_to_delete = await self._simulate_documents(file_hierarchies, changed_groups, group_mapping)


            # Return result
            result = IngestResult(
                group=None,
                documents=[],
                total_files=total_files,
                processed_files=len(files_to_process_indices),
                skipped_files=total_files - len(files_to_process_indices) - len(unsupported_file_indices),
                failed_files=len(unsupported_file_indices),
                failed_details=None,
                files_to_process_indices=files_to_process_indices,
                unsupported_file_indices=unsupported_file_indices,
                files_to_delete=files_to_delete if files_to_delete else None,
            )
            await self.queue.put(PipelineComplete(data=result))

        except Exception as e:
            await self.queue.put(PipelineMessage.error(f"[DRY-RUN] Failed: {str(e)}"))
            await self.queue.put(PipelineComplete(data=None))
            raise

    async def _simulate_groups(self, unique_groups: dict) -> tuple:
        """
        Simulate group operations

        Returns:
            tuple: (changed_groups, group_mapping)
        """
        changed_groups = set()
        group_mapping = {}

        for path, name in unique_groups.items():
            rag_components = self._get_group_rag_components(name)

            needs_work = await simulate_upsert_document_group(
                name=name,
                base_path=path,
                manager_id=self.manager_id,
                rag_components=rag_components,
                force_new_version=False,  # Ignore re_embed in dry-run
                description=self.description if (name == self.group_name) else None,
            )

            # Get actual DocumentGroup for deletion detection
            group = await DocumentGroup.get_or_none(base_path=path)
            if group:
                group_mapping[path] = group

            if needs_work:
                changed_groups.add(name)

        return changed_groups, group_mapping

    async def _simulate_documents(self, file_hierarchies: list, changed_groups: set, group_mapping: dict) -> tuple:
        """
        Simulate document operations

        Args:
            file_hierarchies: File information and hierarchy structure
            changed_groups: Group names with configuration changes

        Returns:
            tuple: (total_count, files_to_process_indices, unsupported_file_indices, files_to_delete)
        """
        files_to_process_indices = []
        unsupported_file_indices = []
        files_to_delete = []

        for idx, (file_info, hierarchy) in enumerate(file_hierarchies):
            try:
                file_path = self.base_path / file_info.relativePath

                # Check if file type is supported
                if not self.loader_manager.supports(file_path):
                    unsupported_file_indices.append(idx)
                    continue

                # Simulate document upsert
                needs_reprocessing = await simulate_upsert_document_from_file(
                    name=Path(file_info.fileName).stem,
                    path=str(file_path.absolute()),
                    size=file_info.size,
                    mtime_ns=int(file_info.createdAt.timestamp() * 1e9),
                    metadata={"original_filename": file_info.fileName},
                )

                # Check which group the file belongs to
                # hierarchy[-1] = (parent_path, name, current_path)
                file_group_name = hierarchy[-1][1]
                group_config_changed = file_group_name in changed_groups

                # File needs processing if changed or group config changed
                if needs_reprocessing or group_config_changed:
                    files_to_process_indices.append(idx)

            except Exception as e:
                await self.queue.put(
                    PipelineMessage.warning(f"  Failed to check {file_info.fileName}: {str(e)}")
                )
                continue

        # Detect files to delete: in DB but not in current files list
        await self._detect_files_to_delete(file_hierarchies, group_mapping, files_to_delete)

        total_count = len(file_hierarchies)
        return total_count, files_to_process_indices, unsupported_file_indices, files_to_delete

    async def _detect_files_to_delete(self, file_hierarchies: list, group_mapping: dict, files_to_delete: list):
        """
        DB에는 있지만 현재 files에 없는 문서들을 감지합니다.

        Args:
            file_hierarchies: 현재 파일 정보 및 계층 구조
            group_mapping: path -> DocumentGroup 매핑
            files_to_delete: 삭제될 파일 이름 리스트 (출력 파라미터)
        """
        # 현재 파일들의 file_path 집합 생성
        current_file_paths = set()
        for file_info, hierarchy in file_hierarchies:
            file_path = self.base_path / file_info.relativePath
            current_file_paths.add(str(file_path.absolute()))

        # 모든 그룹에 속한 문서들 조회
        for group_path, group in group_mapping.items():
            # 해당 그룹의 모든 문서 조회
            memberships = await DocumentGroupMembership.filter(group=group).prefetch_related("document")

            for membership in memberships:
                doc = membership.document

                # 현재 files에 없는 문서 발견
                if doc.file_path not in current_file_paths:
                    files_to_delete.append(doc.name)
