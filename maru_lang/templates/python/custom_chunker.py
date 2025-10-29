"""
Custom chunker template - Copy this file and remove .sample extension

This is a template for creating custom chunking strategies.
Implement the BaseChunker interface to add support for new chunking methods.
"""

from typing import List
from pathlib import Path
from maru_lang.pluggable.chunkers.base import BaseChunker
from maru_lang.models.ingest import ChunkInput


class CustomChunker(BaseChunker):
    """
    커스텀 청킹 전략 템플릿

    이 클래스를 복사하여 새로운 청킹 방식을 구현할 수 있습니다.
    """

    # Chunker 식별 정보
    name = "custom"
    description = "커스텀 청킹 전략"

    def __init__(self, max_chunk_size: int = 500):
        """
        청킹 전략 초기화

        Args:
            max_chunk_size: 청크의 최대 크기
        """
        self.max_chunk_size = max_chunk_size

    def chunk(self, text: str) -> List[ChunkInput]:
        """
        텍스트를 청크로 분할합니다.

        Args:
            text: 전체 텍스트

        Returns:
            List[ChunkInput]: 청크 리스트
        """
        # 여기에 청킹 로직을 구현하세요
        # 예: 특정 구분자로 분할, 의미적 단위로 분할 등

        # 간단한 예제: 문장 단위 분할
        import re
        sentences = re.split(r'[.!?]+\s+', text)
        chunks = []

        for i, sentence in enumerate(sentences, start=1):
            if sentence.strip():
                chunks.append(ChunkInput(
                    number=i,
                    content=sentence.strip(),
                    meta={"chunk_method": "custom"}
                ))

        return chunks


# 예제 1: 헤더 기반 청킹 (마크다운용)
class HeaderBasedChunker(BaseChunker):
    """마크다운 헤더를 기준으로 청킹"""

    name = "header"
    description = "마크다운 헤더 기준 청킹"

    def chunk(self, text: str) -> List[ChunkInput]:
        import re

        # 헤더 패턴 (# 또는 ##로 시작하는 줄)
        header_pattern = r'^(#{1,6})\s+(.+)$'

        chunks = []
        current_chunk = []
        current_header = "Introduction"
        chunk_num = 1

        for line in text.split('\n'):
            header_match = re.match(header_pattern, line, re.MULTILINE)

            if header_match:
                # 이전 청크 저장
                if current_chunk:
                    chunks.append(ChunkInput(
                        number=chunk_num,
                        content='\n'.join(current_chunk),
                        meta={"header": current_header}
                    ))
                    chunk_num += 1

                # 새 청크 시작
                current_header = header_match.group(2)
                current_chunk = [line]
            else:
                current_chunk.append(line)

        # 마지막 청크
        if current_chunk:
            chunks.append(ChunkInput(
                number=chunk_num,
                content='\n'.join(current_chunk),
                meta={"header": current_header}
            ))

        return chunks


# 예제 2: 코드 함수 기반 청킹 (Python 코드용)
class FunctionBasedChunker(BaseChunker):
    """Python 함수/클래스 단위로 청킹"""

    name = "function"
    description = "Python 함수/클래스 단위 청킹"

    def chunk(self, text: str) -> List[ChunkInput]:
        import re

        # 함수/클래스 정의 패턴
        definition_pattern = r'^(def |class )'

        chunks = []
        current_chunk = []
        chunk_num = 1

        for line in text.split('\n'):
            # 새 함수/클래스 정의 발견
            if re.match(definition_pattern, line) and current_chunk:
                # 이전 청크 저장
                chunks.append(ChunkInput(
                    number=chunk_num,
                    content='\n'.join(current_chunk),
                ))
                chunk_num += 1
                current_chunk = []

            current_chunk.append(line)

        # 마지막 청크
        if current_chunk:
            chunks.append(ChunkInput(
                number=chunk_num,
                content='\n'.join(current_chunk),
            ))

        return chunks


# 예제 3: 의미적 청킹 (문장 임베딩 기반)
class SemanticChunker(BaseChunker):
    """의미적 유사도 기반 청킹 (실험적)"""

    name = "semantic"
    description = "의미적 유사도 기반 청킹"

    def __init__(self, similarity_threshold: float = 0.7):
        """
        Args:
            similarity_threshold: 청크를 분리하는 유사도 임계값
        """
        self.similarity_threshold = similarity_threshold

    def chunk(self, text: str) -> List[ChunkInput]:
        # 이 예제는 간단한 버전입니다
        # 실제로는 문장 임베딩을 사용하여 유사도를 계산해야 합니다

        import re
        sentences = re.split(r'[.!?]+\s+', text)

        chunks = []
        current_chunk = []
        chunk_num = 1

        for sentence in sentences:
            if not sentence.strip():
                continue

            # 실제 구현에서는 여기서 이전 문장들과의 유사도를 계산
            # 유사도가 threshold 이하면 새 청크 시작

            if len(current_chunk) >= 5:  # 간단한 예: 5문장마다 분할
                chunks.append(ChunkInput(
                    number=chunk_num,
                    content=' '.join(current_chunk),
                    meta={"chunk_method": "semantic"}
                ))
                chunk_num += 1
                current_chunk = []

            current_chunk.append(sentence.strip())

        # 마지막 청크
        if current_chunk:
            chunks.append(ChunkInput(
                number=chunk_num,
                content=' '.join(current_chunk),
                meta={"chunk_method": "semantic"}
            ))

        return chunks
