"""JSON file parser."""

import json
from pathlib import Path
from .base import BaseParser, ParseResult


class JSONParser(BaseParser):
    """JSON 파일 파서"""

    def parse(self, file_path: Path) -> ParseResult:
        """
        JSON 파일을 읽어 포맷팅된 텍스트로 변환합니다.

        Args:
            file_path: 파싱할 JSON 파일 경로

        Returns:
            ParseResult: 파싱된 텍스트와 메타데이터
        """
        if not file_path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # JSON을 보기 좋게 포맷팅
            content = json.dumps(data, indent=2, ensure_ascii=False)

            metadata = {
                'file_type': 'json',
                'encoding': 'utf-8',
                'file_size': file_path.stat().st_size,
            }

            # 구조 정보 추가
            if isinstance(data, dict):
                metadata['structure'] = 'object'
                metadata['num_keys'] = len(data)
            elif isinstance(data, list):
                metadata['structure'] = 'array'
                metadata['num_items'] = len(data)

            return ParseResult(content=content, metadata=metadata)

        except json.JSONDecodeError as e:
            raise ValueError(f"JSON 파싱 실패: {file_path} - {str(e)}") from e
        except UnicodeDecodeError as e:
            raise ValueError(f"UTF-8 인코딩 오류: {file_path}") from e
        except Exception as e:
            raise ValueError(f"파일 읽기 실패: {file_path}") from e

    def supports(self, file_path: Path) -> bool:
        """JSON 파일 확장자 지원 확인"""
        return file_path.suffix.lower() in self.supported_extensions

    @property
    def supported_extensions(self) -> list[str]:
        """지원하는 JSON 파일 확장자"""
        return ['.json', '.jsonl']
