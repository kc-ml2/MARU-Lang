from abc import ABC, abstractmethod
from typing import List, Optional
from maru_lang.models.ingest import ChunkInput


class BaseChunker(ABC):
    """텍스트 청킹 전략의 기본 인터페이스"""

    # Chunker 식별 정보
    name: str = "base_chunker"
    description: str = "기본 청킹 전략"

    @abstractmethod
    def chunk(self, text: str) -> List[ChunkInput]:
        """전체 텍스트를 받아서 ChunkInput 리스트로 변환"""
        pass

    def get_metadata(self) -> dict:
        """Chunker 메타데이터 반환"""
        return {
            "chunker_name": self.name,
            "chunker_description": self.description,
        }
