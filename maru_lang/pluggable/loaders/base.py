"""Base parser interface for document parsing."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


@dataclass
class ParseResult:
    """파싱 결과를 담는 데이터 클래스"""
    content: str
    metadata: Optional[dict] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class BaseParser(ABC):
    """문서 파싱을 위한 기본 인터페이스"""

    @property
    def default_chunker_name(self) -> Optional[str]:
        """
        이 파서의 기본 chunker 이름

        Returns:
            Optional[str]: chunker 이름 (None이면 전역 기본 chunker 사용)
        """
        return None  # 기본값: None (전역 기본 chunker 사용)

    @abstractmethod
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
        pass

    @abstractmethod
    def supports(self, file_path: Path) -> bool:
        """
        해당 파서가 주어진 파일을 지원하는지 확인합니다.

        Args:
            file_path: 확인할 파일 경로

        Returns:
            bool: 지원 여부
        """
        pass

    @property
    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """
        이 파서가 지원하는 파일 확장자 목록

        Returns:
            list[str]: 지원하는 확장자 리스트 (예: ['.txt', '.text'])
        """
        pass
