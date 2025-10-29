"""PDF file parser."""

from pathlib import Path
from .base import BaseParser, ParseResult


class PDFParser(BaseParser):
    """PDF 파일 파서 (PyPDF2 또는 pdfplumber 사용)"""

    def parse(self, file_path: Path) -> ParseResult:
        """
        PDF 파일에서 텍스트를 추출합니다.

        Args:
            file_path: 파싱할 PDF 파일 경로

        Returns:
            ParseResult: 파싱된 텍스트와 메타데이터
        """
        if not file_path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

        try:
            # PyPDF2 사용 (나중에 pdfplumber로 변경 가능)
            try:
                import PyPDF2
            except ImportError:
                raise ImportError(
                    "PyPDF2가 설치되지 않았습니다. 'pip install PyPDF2'로 설치하세요."
                )

            with open(file_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                num_pages = len(pdf_reader.pages)

                # 모든 페이지에서 텍스트 추출
                text_parts = []
                for page_num in range(num_pages):
                    page = pdf_reader.pages[page_num]
                    text_parts.append(page.extract_text())

                content = '\n\n'.join(text_parts)

            metadata = {
                'file_type': 'pdf',
                'num_pages': num_pages,
                'file_size': file_path.stat().st_size,
            }

            return ParseResult(content=content, metadata=metadata)

        except Exception as e:
            raise ValueError(f"PDF 파싱 실패: {file_path}") from e

    def supports(self, file_path: Path) -> bool:
        """PDF 파일 확장자 지원 확인"""
        return file_path.suffix.lower() in self.supported_extensions

    @property
    def supported_extensions(self) -> list[str]:
        """지원하는 PDF 파일 확장자"""
        return ['.pdf']
