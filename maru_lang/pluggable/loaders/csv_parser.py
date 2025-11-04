"""CSV file parser."""

import csv
from pathlib import Path
from .base import BaseParser, ParseResult


class CSVParser(BaseParser):
    """CSV 파일 파서"""

    def parse(self, file_path: Path) -> ParseResult:
        """
        CSV 파일을 읽어 포맷팅된 텍스트로 변환합니다.

        Args:
            file_path: 파싱할 CSV 파일 경로

        Returns:
            ParseResult: 파싱된 텍스트와 메타데이터
        """
        if not file_path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                # CSV 방언 자동 감지
                sample = f.read(1024)
                f.seek(0)
                sniffer = csv.Sniffer()

                try:
                    dialect = sniffer.sniff(sample)
                    has_header = sniffer.has_header(sample)
                except csv.Error:
                    # 감지 실패시 기본값 사용
                    dialect = csv.excel
                    has_header = True

                reader = csv.reader(f, dialect=dialect)
                rows = list(reader)

            if not rows:
                raise ValueError("CSV 파일이 비어 있습니다")

            # 테이블 형식으로 포맷팅
            if has_header and len(rows) > 1:
                headers = rows[0]
                data_rows = rows[1:]

                # 헤더와 데이터를 구분하여 표시
                content_lines = [
                    f"Headers: {', '.join(headers)}",
                    "=" * 80,
                ]

                for row in data_rows:
                    content_lines.append(' | '.join(str(cell) for cell in row))
            else:
                # 헤더가 없는 경우
                content_lines = []
                for row in rows:
                    content_lines.append(' | '.join(str(cell) for cell in row))

            content = '\n'.join(content_lines)

            metadata = {
                'file_type': 'csv',
                'encoding': 'utf-8',
                'file_size': file_path.stat().st_size,
                'num_rows': len(rows),
                'num_columns': len(rows[0]) if rows else 0,
                'has_header': has_header,
            }

            return ParseResult(content=content, metadata=metadata)

        except UnicodeDecodeError as e:
            raise ValueError(f"UTF-8 인코딩 오류: {file_path}") from e
        except Exception as e:
            raise ValueError(f"CSV 파싱 실패: {file_path}") from e

    def supports(self, file_path: Path) -> bool:
        """CSV 파일 확장자 지원 확인"""
        return file_path.suffix.lower() in self.supported_extensions

    @property
    def supported_extensions(self) -> list[str]:
        """지원하는 CSV 파일 확장자"""
        return ['.csv', '.tsv']
