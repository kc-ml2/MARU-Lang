"""YAML file parser."""

from pathlib import Path
from .base import BaseParser, ParseResult


class YAMLParser(BaseParser):
    """YAML 파일 파서"""

    def parse(self, file_path: Path) -> ParseResult:
        """
        YAML 파일을 읽어 포맷팅된 텍스트로 변환합니다.

        Args:
            file_path: 파싱할 YAML 파일 경로

        Returns:
            ParseResult: 파싱된 텍스트와 메타데이터
        """
        if not file_path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

        try:
            try:
                import yaml
            except ImportError:
                raise ImportError(
                    "pyyaml이 설치되지 않았습니다. 'pip install pyyaml'로 설치하세요."
                )

            with open(file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            # YAML을 보기 좋게 포맷팅
            content = yaml.dump(
                data,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
                indent=2,
            )

            metadata = {
                'file_type': 'yaml',
                'encoding': 'utf-8',
                'file_size': file_path.stat().st_size,
            }

            # 구조 정보 추가
            if isinstance(data, dict):
                metadata['structure'] = 'mapping'
                metadata['num_keys'] = len(data)
            elif isinstance(data, list):
                metadata['structure'] = 'sequence'
                metadata['num_items'] = len(data)

            return ParseResult(content=content, metadata=metadata)

        except yaml.YAMLError as e:
            raise ValueError(f"YAML 파싱 실패: {file_path} - {str(e)}") from e
        except UnicodeDecodeError as e:
            raise ValueError(f"UTF-8 인코딩 오류: {file_path}") from e
        except Exception as e:
            raise ValueError(f"파일 읽기 실패: {file_path}") from e

    def supports(self, file_path: Path) -> bool:
        """YAML 파일 확장자 지원 확인"""
        return file_path.suffix.lower() in self.supported_extensions

    @property
    def supported_extensions(self) -> list[str]:
        """지원하는 YAML 파일 확장자"""
        return ['.yaml', '.yml']
