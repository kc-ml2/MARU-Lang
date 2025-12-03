"""
MaruSync version of IngestPipeline
"""
from pathlib import Path
from typing import List

from maru_lang.enums.documents import SyncMode
from maru_lang.pipelines.base import PipelineMessage
from maru_lang.pipelines.ingest.pipeline import IngestPipeline
from maru_lang.schemas.ingest import FileInfo
from maru_lang.core.sync import sync_request



class MaruSyncIngestPipeline(IngestPipeline):
    """
    MaruSync version of IngestPipeline

    Syncs files to MaruSync server
    """

    def __init__(
        self,
        files: List[FileInfo],
        group_name: str,
        manager_id: int,
        base_path: Path,
        user_id: int
    ):
        super().__init__(
            files,
            group_name,
            manager_id,
            base_path
        )
        self.user_id = user_id

    async def _create_groups(
        self,
        unique_groups: dict,
        sync_mode: SyncMode = SyncMode.CLIENT
    ):
        """
        Create groups and set group relationships
        """
        return await super()._create_groups(unique_groups, sync_mode)

    async def _delete_document_chunks(self, doc) -> int:
        """
        VDB에서 문서의 청크를 삭제합니다.
        MaruSync version: Uses sync_request to delegate to client

        Args:
            doc: Document 객체

        Returns:
            int: 삭제된 청크 수
        """
        try:
            response = await sync_request(
                user_id=self.user_id,
                action="delete_chunks",
                data={
                    "document_id": doc.id,
                    "document_name": doc.name
                },
                timeout=30.0
            )
            return response.get("deleted_count", 0)
        except TimeoutError:
            await self.queue.put(
                PipelineMessage.warning(f"Timeout deleting chunks for {doc.name}")
            )
            return 0
        except Exception as e:
            await self.queue.put(
                PipelineMessage.warning(f"Failed to delete chunks for {doc.name}: {str(e)}")
            )
            return 0

    async def _add_document_chunks_to_vdb(
        self,
        doc,
        vdb_documents: list[dict],
        vectors: list[list[float]]
    ) -> int:
        """
        VDB에 문서의 청크를 추가합니다.
        MaruSync version: Uses sync_request to delegate to client

        Args:
            doc: Document 객체
            vdb_documents: VDB에 저장할 문서 리스트
            vectors: 임베딩 벡터 리스트

        Returns:
            int: 저장된 청크 수
        """
        response = await sync_request(
            user_id=self.user_id,
            action="add_documents",
            data={
                "documents": vdb_documents,
                "embeddings": vectors,
                "document_name": doc.name
            },
            timeout=60.0  # 임베딩 저장은 시간이 더 걸릴 수 있음
        )
        return response.get("chunks_saved", len(vdb_documents))