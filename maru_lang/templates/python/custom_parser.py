"""
Custom parser template - Copy this file and remove .sample extension

This is a template for creating custom document parsers.
Implement the BaseParser interface to add support for new file formats.
"""

from pathlib import Path
from maru_lang.pluggable.loaders.base import BaseParser, ParseResult


class CustomParser(BaseParser):
    """
    커스텀 파일 파서 템플릿

    이 클래스를 복사하여 새로운 파일 형식을 지원하는 파서를 만들 수 있습니다.
    """

    def parse(self, file_path: Path) -> ParseResult:
        """
        파일을 파싱하여 텍스트 콘텐츠를 추출합니다.

        Args:
            file_path: 파싱할 파일의 경로

        Returns:
            ParseResult: 파싱된 텍스트와 메타데이터

        Raises:
            ValueError: 파일을 읽을 수 없거나 파싱할 수 없는 경우
            FileNotFoundError: 파일이 존재하지 않는 경우
        """
        if not file_path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

        try:
            # 여기에 파싱 로직을 구현하세요
            # 예: JSON, XML, CSV 등의 형식을 텍스트로 변환

            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 메타데이터 추가 (선택사항)
            metadata = {
                'file_type': 'custom',
                'file_size': file_path.stat().st_size,
                # 필요한 다른 메타데이터 추가
            }

            return ParseResult(content=content, metadata=metadata)

        except Exception as e:
            raise ValueError(f"파일 파싱 실패: {file_path}") from e

    def supports(self, file_path: Path) -> bool:
        """
        해당 파서가 주어진 파일을 지원하는지 확인합니다.

        Args:
            file_path: 확인할 파일 경로

        Returns:
            bool: 지원 여부
        """
        return file_path.suffix.lower() in self.supported_extensions

    @property
    def supported_extensions(self) -> list[str]:
        """
        이 파서가 지원하는 파일 확장자 목록

        Returns:
            list[str]: 지원하는 확장자 리스트 (예: ['.json', '.jsonl'])
        """
        # 여기에 지원할 확장자를 나열하세요
        return ['.custom', '.cst']


# 예제: JSON 파서
class JsonParser(BaseParser):
    """JSON 파일 파서 예제"""

    def parse(self, file_path: Path) -> ParseResult:
        if not file_path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

        try:
            import json

            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # JSON을 포맷된 텍스트로 변환
            content = json.dumps(data, indent=2, ensure_ascii=False)

            metadata = {
                'file_type': 'json',
                'file_size': file_path.stat().st_size,
            }

            return ParseResult(content=content, metadata=metadata)

        except json.JSONDecodeError as e:
            raise ValueError(f"JSON 파싱 오류: {file_path}") from e
        except Exception as e:
            raise ValueError(f"파일 읽기 실패: {file_path}") from e

    def supports(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.supported_extensions

    @property
    def supported_extensions(self) -> list[str]:
        return ['.json', '.jsonl']
