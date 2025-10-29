from typing import List
from maru_lang.models.ingest import ChunkInput
from .base import BaseChunker


class ParagraphChunker(BaseChunker):
    """문단 단위로 청킹 (개행 2개 기준)"""

    name = "paragraph"
    description = "문단 단위로 청킹 (빈 줄 기준 분리)"

    def __init__(self, max_chunk_size: int = 500):
        self.max_chunk_size = max_chunk_size

    def chunk(self, text: str) -> List[ChunkInput]:
        parts = [p.strip() for p in text.split("\n\n") if p.strip()]
        return [ChunkInput(number=i, content=p) for i, p in enumerate(parts, start=1)]
