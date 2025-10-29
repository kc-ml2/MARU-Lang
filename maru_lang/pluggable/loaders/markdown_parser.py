"""Markdown file parser."""

from pathlib import Path
from .base import BaseParser, ParseResult


class MarkdownParser(BaseParser):
    """마크다운 파일 파서"""

    def parse(self, file_path: Path) -> ParseResult:
        """
        마크다운 파일을 읽어 내용을 반환합니다.
        (나중에 HTML 변환 등의 추가 처리 가능)

        Args:
            file_path: 파싱할 마크다운 파일 경로

        Returns:
            ParseResult: 파싱된 텍스트와 메타데이터
        """
        if not file_path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            metadata = {
                'file_type': 'markdown',
                'encoding': 'utf-8',
                'file_size': file_path.stat().st_size,
            }

            return ParseResult(content=content, metadata=metadata)

        except UnicodeDecodeError as e:
            raise ValueError(f"UTF-8 인코딩 오류: {file_path}") from e
        except Exception as e:
            raise ValueError(f"파일 읽기 실패: {file_path}") from e

    def supports(self, file_path: Path) -> bool:
        """마크다운 파일 확장자 지원 확인"""
        return file_path.suffix.lower() in self.supported_extensions

    @property
    def supported_extensions(self) -> list[str]:
        """지원하는 마크다운 파일 확장자"""
        return ['.md', '.markdown', '.mdown', '.mkd']
