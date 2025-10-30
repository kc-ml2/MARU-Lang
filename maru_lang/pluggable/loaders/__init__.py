"""Loader for handling multiple document formats."""

import sys
import inspect
import importlib.util
import logging
from pathlib import Path
from typing import Optional, Dict, Type
from .base import BaseParser, ParseResult
from .txt_parser import TxtParser
from .markdown_parser import MarkdownParser
from .pdf_parser import PDFParser
from .docx_parser import DocxParser
from .html_parser import HTMLParser

logger = logging.getLogger(__name__)


class Loader:
    """
    파일 타입에 따라 적절한 파서를 선택하고 실행하는 매니저
    """

    def __init__(self, user_parsers_dir: Optional[Path] = None):
        """
        기본 파서와 사용자 정의 파서를 등록합니다.

        Args:
            user_parsers_dir: 사용자 정의 파서 디렉토리 경로
                             (기본값: 현재 디렉토리/loaders)
        """
        self._parsers: Dict[str, BaseParser] = {}
        self._parser_sources: Dict[str, str] = {}  # 어떤 파서가 어디서 왔는지 추적
        self._chunker_mapping: Dict[str, str] = {}  # 확장자 -> chunker 이름 매핑
        self._default_chunker: str = "paragraph"  # 기본 chunker
        self._default_loader: Optional[str] = None  # 기본 loader (None이면 whitelist 모드)

        # 1. 기본 파서 등록
        self._register_default_parsers()

        # 2. 사용자 파서 로드 (기본 파서를 override)
        if user_parsers_dir is None:
            user_parsers_dir = Path.cwd() / "loaders"
        self._load_user_parsers(user_parsers_dir)

        # 3. Loader config 로드 (확장자 -> loader + chunker 매핑)
        self._load_loader_config()

    def _register_default_parsers(self):
        """기본 제공되는 파서들을 등록합니다."""
        default_parsers = [
            TxtParser(),
            MarkdownParser(),
            PDFParser(),
            DocxParser(),
            HTMLParser(),
        ]

        for parser in default_parsers:
            parser_name = parser.__class__.__name__
            for ext in parser.supported_extensions:
                self._parsers[ext] = parser
                self._parser_sources[ext] = f"builtin:{parser_name}"

    def _load_user_parsers(self, user_parsers_dir: Path):
        """
        사용자 정의 파서 디렉토리에서 파서를 로드합니다.

        Args:
            user_parsers_dir: 사용자 파서 디렉토리 경로
        """
        if not user_parsers_dir.exists() or not user_parsers_dir.is_dir():
            return

        # .py 파일을 알파벳 순으로 로드 (마지막이 우선)
        py_files = sorted(user_parsers_dir.glob("*.py"))

        for py_file in py_files:
            # __init__.py나 .sample 파일은 건너뛰기
            if py_file.name == "__init__.py" or ".sample" in py_file.name:
                continue

            try:
                # 동적으로 모듈 로드
                module_name = f"user_parser_{py_file.stem}"
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec is None or spec.loader is None:
                    logger.warning(f"파서 로드 실패: {py_file}")
                    continue

                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                # 모듈에서 BaseParser를 상속한 클래스 찾기
                parser_classes_found = 0
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    # BaseParser를 상속하고, BaseParser 자체가 아닌 클래스
                    if issubclass(obj, BaseParser) and obj is not BaseParser:
                        try:
                            parser_instance = obj()
                            self._register_user_parser(
                                parser_instance,
                                source=f"user:{py_file.name}"
                            )
                            parser_classes_found += 1
                        except Exception as e:
                            logger.error(
                                f"파서 인스턴스 생성 실패 ({name} in {py_file.name}): {e}"
                            )

                if parser_classes_found == 0:
                    logger.warning(
                        f"BaseParser를 상속한 클래스를 찾을 수 없습니다: {py_file.name}"
                    )
                else:
                    logger.info(
                        f"사용자 파서 로드 완료: {py_file.name} "
                        f"({parser_classes_found}개 파서)"
                    )

            except Exception as e:
                logger.error(f"파서 파일 로드 실패 ({py_file.name}): {e}")

    def _load_loader_config(self):
        """
        ConfigManager를 사용하여 loader_config.yaml을 로드하고
        확장자별 chunker 매핑 및 default 설정을 적용합니다.
        """
        try:
            from maru_lang.configs import get_config_manager

            config_manager = get_config_manager()
            merged_config = config_manager.get_loader_config()

            if not merged_config:
                logger.debug("Loader 설정이 없습니다.")
                return

            # Default loader/chunker 설정
            if merged_config.default_loader:
                self._default_loader = merged_config.default_loader
                logger.debug(f"기본 loader 설정: {self._default_loader}")

            if merged_config.default_chunker:
                self._default_chunker = merged_config.default_chunker
                logger.debug(f"기본 chunker 설정: {self._default_chunker}")

            # extensions 매핑에서 chunker 정보 추출
            if merged_config.extensions:
                for ext, mapping in merged_config.extensions.items():
                    ext_lower = ext.lower()
                    self._chunker_mapping[ext_lower] = mapping.chunker

                    # loader 이름 로깅 (검증 용도)
                    logger.debug(
                        f"확장자 {ext}: loader={mapping.loader}, chunker={mapping.chunker}"
                    )

                logger.info(
                    f"Loader config 로드 완료: {len(self._chunker_mapping)}개 확장자, "
                    f"default_loader={self._default_loader}, default_chunker={self._default_chunker}"
                )

        except ImportError as e:
            logger.warning(f"ConfigManager를 import할 수 없습니다: {e}")
        except Exception as e:
            logger.error(f"Loader config 로드 실패: {e}")

    def _register_user_parser(self, parser: BaseParser, source: str):
        """
        사용자 정의 파서를 등록하고 충돌을 감지합니다.

        Args:
            parser: 등록할 파서 인스턴스
            source: 파서 출처 정보 (예: "user:json_parser.py")
        """
        parser_name = parser.__class__.__name__

        for ext in parser.supported_extensions:
            # 기존 파서가 있는지 확인
            if ext in self._parsers:
                old_source = self._parser_sources.get(ext, "unknown")
                logger.warning(
                    f"파서 충돌: 확장자 '{ext}'는 이미 {old_source}에 의해 등록됨. "
                    f"{source}:{parser_name}으로 덮어씁니다."
                )

            # 파서 등록 (덮어쓰기)
            self._parsers[ext] = parser
            self._parser_sources[ext] = f"{source}:{parser_name}"

    def register_parser(self, parser: BaseParser, source: str = "custom"):
        """
        새로운 파서를 등록합니다.

        Args:
            parser: 등록할 파서 인스턴스
            source: 파서 출처 정보
        """
        self._register_user_parser(parser, source)

    def get_parser(self, file_path: Path) -> Optional[BaseParser]:
        """
        파일 확장자에 맞는 파서를 반환합니다.
        확장자 매핑이 없으면 default_loader를 fallback으로 사용합니다.

        Args:
            file_path: 파싱할 파일 경로

        Returns:
            Optional[BaseParser]: 해당 확장자를 지원하는 파서, 없으면 None
        """
        ext = file_path.suffix.lower()

        # 1. 확장자 직접 매핑 확인
        parser = self._parsers.get(ext)
        if parser:
            return parser

        # 2. default_loader fallback
        if self._default_loader:
            default_ext = f".{self._default_loader}" if not self._default_loader.startswith('.') else self._default_loader
            fallback_parser = self._parsers.get(default_ext)
            if fallback_parser:
                logger.debug(
                    f"확장자 '{ext}' 매핑 없음, default_loader '{self._default_loader}' 사용"
                )
                return fallback_parser

        return None

    def parse(self, file_path: Path) -> ParseResult:
        """
        파일을 파싱합니다.

        Args:
            file_path: 파싱할 파일 경로

        Returns:
            ParseResult: 파싱 결과

        Raises:
            ValueError: 지원하지 않는 파일 형식인 경우
            FileNotFoundError: 파일이 존재하지 않는 경우
        """
        if not isinstance(file_path, Path):
            file_path = Path(file_path)

        parser = self.get_parser(file_path)
        if parser is None:
            ext = file_path.suffix.lower()
            error_msg = f"❌ 파일을 로드할 수 없습니다: {file_path.name}\n"
            error_msg += f"   확장자 '{ext}'에 대한 loader 매핑이 없습니다.\n"
            if self._default_loader:
                error_msg += f"   default_loader '{self._default_loader}'도 사용할 수 없습니다.\n"
            error_msg += f"   지원 가능한 확장자: {', '.join(sorted(self._parsers.keys()))}\n"
            error_msg += f"   💡 loader_config.yaml에서 확장자 매핑을 추가하거나 default_loader를 설정하세요."
            raise ValueError(error_msg)

        try:
            return parser.parse(file_path)
        except Exception as e:
            error_msg = f"❌ 파일 파싱 중 오류 발생: {file_path.name}\n"
            error_msg += f"   사용된 parser: {parser.__class__.__name__}\n"
            error_msg += f"   오류: {str(e)}"
            logger.error(error_msg)
            raise

    def supports(self, file_path: Path) -> bool:
        """
        해당 파일을 파싱할 수 있는지 확인합니다.

        Args:
            file_path: 확인할 파일 경로

        Returns:
            bool: 지원 여부
        """
        if not isinstance(file_path, Path):
            file_path = Path(file_path)

        return self.get_parser(file_path) is not None

    @property
    def supported_extensions(self) -> list[str]:
        """
        현재 등록된 모든 파서가 지원하는 확장자 목록

        Returns:
            list[str]: 지원하는 확장자 리스트
        """
        return sorted(self._parsers.keys())

    def get_chunker_name_for_file(self, file_path: Path) -> str:
        """
        파일 확장자에 맞는 chunker 이름을 반환합니다.

        Args:
            file_path: 파일 경로

        Returns:
            str: chunker 이름 (설정에 없으면 기본값)
        """
        if not isinstance(file_path, Path):
            file_path = Path(file_path)

        ext = file_path.suffix.lower()
        return self._chunker_mapping.get(ext, self._default_chunker)


# 싱글톤 인스턴스
_loader_instance: Optional[Loader] = None


def get_loader(
    user_parsers_dir: Optional[Path] = None,
    force_new: bool = False,
) -> Loader:
    """
    Loader 싱글톤 인스턴스 반환

    Args:
        user_parsers_dir: 사용자 정의 파서 디렉토리 경로 (None이면 기본값)
        force_new: True면 기존 인스턴스 무시하고 새로 생성 (테스트용)

    Returns:
        Loader: 싱글톤 인스턴스

    Example:
        >>> loader = get_loader()
        >>> result = loader.parse(Path("document.pdf"))
    """
    global _loader_instance

    if _loader_instance is None or force_new:
        _loader_instance = Loader(user_parsers_dir=user_parsers_dir)

    return _loader_instance


# 편의를 위한 함수
def parse_file(file_path: Path) -> ParseResult:
    """
    파일을 파싱하는 편의 함수

    Args:
        file_path: 파싱할 파일 경로

    Returns:
        ParseResult: 파싱 결과
    """
    return get_loader().parse(file_path)


__all__ = [
    'BaseParser',
    'ParseResult',
    'Loader',
    'TxtParser',
    'MarkdownParser',
    'PDFParser',
    'DocxParser',
    'HTMLParser',
    'get_loader',
    'parse_file',
]
