from typing import List
from maru_lang.models.ingest import ChunkInput
from .base import BaseChunker


class ParagraphChunker(BaseChunker):
    """문단 단위로 청킹 (개행 2개 기준)"""

    name = "paragraph"
    description = "문단 단위로 청킹 (빈 줄 기준 분리)"

    def __init__(self, max_chunk_size: int = 2000):
        self.max_chunk_size = max_chunk_size

    def chunk(self, text: str) -> List[ChunkInput]:
        parts = [p.strip() for p in text.split("\n\n") if p.strip()]

        # 큰 청크를 max_chunk_size 기준으로 분할
        chunks = []
        for part in parts:
            if len(part) <= self.max_chunk_size:
                chunks.append(part)
            else:
                # 큰 청크를 문장 단위로 분할 시도
                sentences = self._split_by_sentences(part)
                current_chunk = []
                current_size = 0

                for sentence in sentences:
                    sentence_len = len(sentence)

                    # 단일 문장이 max_chunk_size를 초과하는 경우
                    if sentence_len > self.max_chunk_size:
                        # 현재 버퍼가 있으면 먼저 저장
                        if current_chunk:
                            chunks.append(" ".join(current_chunk))
                            current_chunk = []
                            current_size = 0
                        # 큰 문장을 강제로 분할
                        chunks.extend(self._force_split(sentence, self.max_chunk_size))
                        continue

                    # 현재 청크에 추가했을 때 크기 초과 여부 확인
                    if current_size + sentence_len + (1 if current_chunk else 0) > self.max_chunk_size:
                        # 현재 버퍼 저장
                        if current_chunk:
                            chunks.append(" ".join(current_chunk))
                        current_chunk = [sentence]
                        current_size = sentence_len
                    else:
                        current_chunk.append(sentence)
                        current_size += sentence_len + (1 if len(current_chunk) > 1 else 0)

                # 남은 버퍼 저장
                if current_chunk:
                    chunks.append(" ".join(current_chunk))

        # 안전장치: 모든 청크가 max_chunk_size 이하인지 검증하고 필요시 재분할
        final_chunks = []
        for chunk in chunks:
            if len(chunk) <= self.max_chunk_size:
                final_chunks.append(chunk)
            else:
                # max_chunk_size를 초과하는 청크는 강제 분할
                final_chunks.extend(self._force_split(chunk, self.max_chunk_size))

        return [ChunkInput(number=i, content=c) for i, c in enumerate(final_chunks, start=1)]

    def _split_by_sentences(self, text: str) -> List[str]:
        """텍스트를 문장 단위로 분할 (간단한 휴리스틱)"""
        import re
        # 한글/영어 문장 종결 기호로 분할
        sentences = re.split(r'([.!?。！？\n]+)', text)

        # 구두점을 앞 문장에 붙이기
        result = []
        for i in range(0, len(sentences) - 1, 2):
            if i + 1 < len(sentences):
                result.append((sentences[i] + sentences[i + 1]).strip())
            else:
                result.append(sentences[i].strip())

        # 마지막 요소가 남아있으면 추가
        if len(sentences) % 2 == 1 and sentences[-1].strip():
            result.append(sentences[-1].strip())

        return [s for s in result if s]

    def _force_split(self, text: str, max_size: int) -> List[str]:
        """max_size보다 큰 텍스트를 강제로 분할"""
        chunks = []
        for i in range(0, len(text), max_size):
            chunks.append(text[i:i + max_size])
        return chunks
