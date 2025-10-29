import re
from typing import List
from maru_lang.models.ingest import ChunkInput
from .base import BaseChunker


class SentenceChunker(BaseChunker):
    """문장 단위로 청킹 (마침표/물음표/느낌표 기준), 최대 크기 제한"""

    name = "sentence"
    description = "문장 단위로 청킹하고 최대 크기에 맞춰 병합"

    def __init__(self, max_chunk_size: int = 500):
        self.max_chunk_size = max_chunk_size

    def chunk(self, text: str) -> List[ChunkInput]:
        # 한글/영문 문장 끝 패턴
        sentence_pattern = r'[.!?]+[\s\n]+'
        sentences = [s.strip() for s in re.split(sentence_pattern, text) if s.strip()]

        chunks = []
        current_chunk = []
        current_size = 0
        chunk_num = 1

        for sentence in sentences:
            sentence_len = len(sentence)

            if current_size + sentence_len > self.max_chunk_size and current_chunk:
                # 현재 청크 저장
                chunks.append(ChunkInput(
                    number=chunk_num,
                    content=' '.join(current_chunk)
                ))
                chunk_num += 1
                current_chunk = []
                current_size = 0

            current_chunk.append(sentence)
            current_size += sentence_len

        # 마지막 청크
        if current_chunk:
            chunks.append(ChunkInput(
                number=chunk_num,
                content=' '.join(current_chunk)
            ))

        return chunks
