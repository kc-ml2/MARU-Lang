from typing import List
from maru_lang.models.ingest import ChunkInput
from .base import BaseChunker


class FixedSizeChunker(BaseChunker):
    """고정 크기(문자 수) 기준으로 청킹, 오버랩 지원, 단어 경계 보존"""

    name = "fixed_size"
    description = "고정 크기로 청킹하며 오버랩 지원, 단어 경계를 존중하여 자연스럽게 분할"

    def __init__(self, chunk_size: int = 1000, overlap: int = 200, respect_word_boundary: bool = True):
        """
        Args:
            chunk_size: 목표 청크 크기 (문자 수)
            overlap: 청크 간 오버랩 크기 (문자 수)
            respect_word_boundary: True면 단어 경계에서 분할 (기본값), False면 정확한 크기로 자름
        """
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.respect_word_boundary = respect_word_boundary

    def chunk(self, text: str) -> List[ChunkInput]:
        chunks = []
        start = 0
        chunk_num = 1
        text_len = len(text)

        while start < text_len:
            # 목표 끝 위치 계산
            end = min(start + self.chunk_size, text_len)

            # 단어 경계 존중이 활성화되어 있고, 텍스트 끝이 아닌 경우
            if self.respect_word_boundary and end < text_len:
                # 목표 위치 근처에서 적절한 분할 지점 찾기
                end = self._find_split_point(text, start, end)

            chunk_text = text[start:end].strip()

            if chunk_text:
                chunks.append(ChunkInput(number=chunk_num, content=chunk_text))
                chunk_num += 1

            # 다음 청크 시작 위치 계산
            if self.overlap > 0 and end < text_len:
                # 오버랩을 고려한 다음 시작 위치
                next_start = end - self.overlap

                # 오버랩 영역에서 단어 경계 찾기 (역방향)
                if self.respect_word_boundary:
                    next_start = self._find_overlap_start(text, next_start, end)

                start = max(next_start, start + 1)  # 무한 루프 방지
            else:
                start = end

        return chunks

    def _find_split_point(self, text: str, start: int, target_end: int) -> int:
        """
        목표 위치 근처에서 최적의 분할 지점을 찾습니다.
        우선순위: 문단 > 문장 > 단어 경계

        Args:
            text: 전체 텍스트
            start: 현재 청크 시작 위치
            target_end: 목표 끝 위치

        Returns:
            실제 분할 위치
        """
        # 검색 범위: target_end 전후 10% 범위
        search_range = max(50, int(self.chunk_size * 0.1))
        search_start = max(start, target_end - search_range)
        search_end = min(len(text), target_end + search_range)

        search_text = text[search_start:search_end]

        # 1. 문단 경계 찾기 (빈 줄)
        paragraph_breaks = [i for i, char in enumerate(search_text) if char == '\n']
        if paragraph_breaks:
            # target_end에 가장 가까운 줄바꿈 찾기
            target_offset = target_end - search_start
            closest_break = min(paragraph_breaks, key=lambda x: abs(x - target_offset))

            # 연속된 줄바꿈이면 문단 경계
            abs_pos = search_start + closest_break
            if abs_pos + 1 < len(text) and text[abs_pos:abs_pos+2] == '\n\n':
                return abs_pos + 2

            # 단일 줄바꿈 뒤에 공백이 있으면 문단 경계로 간주
            if abs_pos + 1 < len(text) and text[abs_pos + 1] in ' \t':
                return abs_pos + 1

        # 2. 문장 경계 찾기 (마침표, 물음표, 느낌표)
        sentence_enders = '.!?。！？'
        for i in range(len(search_text) - 1, -1, -1):
            abs_pos = search_start + i
            if search_text[i] in sentence_enders:
                # 문장 부호 다음이 공백이거나 줄바꿈이면 문장 끝
                if i + 1 < len(search_text) and search_text[i + 1] in ' \n\t':
                    return abs_pos + 2 if abs_pos + 2 <= len(text) else abs_pos + 1
                # 텍스트 끝이면 문장 끝
                if i + 1 == len(search_text):
                    return abs_pos + 1

        # 3. 단어 경계 찾기 (공백, 탭, 줄바꿈)
        whitespace_chars = ' \n\t'
        for i in range(len(search_text) - 1, -1, -1):
            abs_pos = search_start + i
            if search_text[i] in whitespace_chars:
                # 공백 위치의 다음 문자부터 시작
                return abs_pos + 1 if abs_pos + 1 <= len(text) else abs_pos

        # 4. 적절한 분할점을 못 찾은 경우 목표 위치 반환
        return target_end

    def _find_overlap_start(self, text: str, target_start: int, chunk_end: int) -> int:
        """
        오버랩 시작 위치를 단어 경계에서 찾습니다.

        Args:
            text: 전체 텍스트
            target_start: 목표 시작 위치
            chunk_end: 이전 청크의 끝 위치

        Returns:
            실제 오버랩 시작 위치
        """
        # 오버랩 영역이 너무 작으면 그냥 반환
        if chunk_end - target_start < 10:
            return target_start

        # target_start부터 chunk_end 사이에서 단어 시작점 찾기
        search_range = text[target_start:chunk_end]

        # 공백 다음의 첫 문자 찾기 (단어 시작)
        for i, char in enumerate(search_range):
            if char not in ' \n\t':
                # 이전 문자가 공백이면 단어 시작점
                if i == 0 or search_range[i-1] in ' \n\t':
                    return target_start + i

        # 적절한 위치를 못 찾으면 목표 위치 반환
        return target_start
