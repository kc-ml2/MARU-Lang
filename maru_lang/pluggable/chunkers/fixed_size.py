from typing import List
from maru_lang.models.ingest import ChunkInput
from .base import BaseChunker


class FixedSizeChunker(BaseChunker):
    """고정 크기(문자 수) 기준으로 청킹, 오버랩 지원"""

    name = "fixed_size"
    description = "고정 크기로 청킹하며 오버랩 지원"

    def __init__(self, chunk_size: int = 500, overlap: int = 200):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, text: str) -> List[ChunkInput]:
        chunks = []
        start = 0
        chunk_num = 1

        while start < len(text):
            end = start + self.chunk_size
            chunk_text = text[start:end].strip()

            if chunk_text:
                chunks.append(ChunkInput(number=chunk_num, content=chunk_text))
                chunk_num += 1

            start = end - self.overlap if self.overlap > 0 else end

        return chunks
