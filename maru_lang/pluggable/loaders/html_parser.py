"""HTML file parser."""

from pathlib import Path
from .base import BaseParser, ParseResult


class HTMLParser(BaseParser):
    """HTML 파일 파서 (BeautifulSoup 사용)"""

    def parse(self, file_path: Path) -> ParseResult:
        """
        HTML 파일에서 텍스트를 추출합니다.

        Args:
            file_path: 파싱할 HTML 파일 경로

        Returns:
            ParseResult: 파싱된 텍스트와 메타데이터
        """
        if not file_path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

        try:
            try:
                from bs4 import BeautifulSoup
            except ImportError:
                raise ImportError(
                    "beautifulsoup4가 설치되지 않았습니다. 'pip install beautifulsoup4'로 설치하세요."
                )

            with open(file_path, 'r', encoding='utf-8') as f:
                html_content = f.read()

            soup = BeautifulSoup(html_content, 'html.parser')

            # script와 style 태그 제거
            for script in soup(['script', 'style']):
                script.decompose()

            # 텍스트 추출
            text = soup.get_text(separator='\n', strip=True)

            # 연속된 빈 줄 제거
            lines = [line.strip() for line in text.split('\n')]
            content = '\n'.join(line for line in lines if line)

            metadata = {
                'file_type': 'html',
                'encoding': 'utf-8',
                'file_size': file_path.stat().st_size,
            }

            # 메타 태그에서 추가 정보 추출 (옵션)
            if soup.title:
                metadata['title'] = soup.title.string

            return ParseResult(content=content, metadata=metadata)

        except UnicodeDecodeError as e:
            raise ValueError(f"UTF-8 인코딩 오류: {file_path}") from e
        except Exception as e:
            raise ValueError(f"HTML 파싱 실패: {file_path}") from e

    def supports(self, file_path: Path) -> bool:
        """HTML 파일 확장자 지원 확인"""
        return file_path.suffix.lower() in self.supported_extensions

    @property
    def supported_extensions(self) -> list[str]:
        """지원하는 HTML 파일 확장자"""
        return ['.html', '.htm', '.xhtml']
