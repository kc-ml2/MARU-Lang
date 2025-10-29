"""Chunker for handling multiple chunking strategies."""

import sys
import inspect
import importlib.util
import logging
from pathlib import Path
from typing import Optional, Dict

from .base import BaseChunker
from .paragraph import ParagraphChunker
from .fixed_size import FixedSizeChunker
from .sentence import SentenceChunker

logger = logging.getLogger(__name__)


class Chunker:
    """
    다양한 청킹 전략을 관리하는 매니저
    name 기반으로 chunker를 선택하고 실행
    """

    def __init__(self, user_chunkers_dir: Optional[Path] = None):
        """
        기본 chunker와 사용자 정의 chunker를 등록합니다.

        Args:
            user_chunkers_dir: 사용자 정의 chunker 디렉토리 경로
                             (기본값: 현재 디렉토리/chunkers)
        """
        self._chunkers: Dict[str, BaseChunker] = {}
        self._chunker_sources: Dict[str, str] = {}  # 어떤 chunker가 어디서 왔는지 추적

        # 1. 기본 chunker 등록
        self._register_default_chunkers()

        # 2. 사용자 chunker 로드 (기본 chunker를 override)
        if user_chunkers_dir is None:
            user_chunkers_dir = Path.cwd() / "chunkers"
        self._load_user_chunkers(user_chunkers_dir)

        # 3. Chunker config 로드 (chunker 파라미터 적용)
        self._load_chunker_config()

    def _register_default_chunkers(self):
        """기본 제공되는 chunker들을 등록합니다."""
        default_chunkers = [
            ParagraphChunker(),
            SentenceChunker(),
            FixedSizeChunker(),
        ]

        for chunker in default_chunkers:
            chunker_name = chunker.name
            self._chunkers[chunker_name] = chunker
            self._chunker_sources[chunker_name] = f"builtin:{chunker.__class__.__name__}"
            logger.debug(f"기본 chunker 등록: {chunker_name}")

    def _load_user_chunkers(self, user_chunkers_dir: Path):
        """
        사용자 정의 chunker 디렉토리에서 chunker를 로드합니다.

        Args:
            user_chunkers_dir: 사용자 chunker 디렉토리 경로
        """
        if not user_chunkers_dir.exists() or not user_chunkers_dir.is_dir():
            return

        # .py 파일을 알파벳 순으로 로드 (마지막이 우선)
        py_files = sorted(user_chunkers_dir.glob("*.py"))

        for py_file in py_files:
            # __init__.py나 .sample 파일은 건너뛰기
            if py_file.name == "__init__.py" or ".sample" in py_file.name:
                continue

            try:
                # 동적으로 모듈 로드
                module_name = f"user_chunker_{py_file.stem}"
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec is None or spec.loader is None:
                    logger.warning(f"Chunker 로드 실패: {py_file}")
                    continue

                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                # 모듈에서 BaseChunker를 상속한 클래스 찾기
                chunker_classes_found = 0
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    # BaseChunker를 상속하고, BaseChunker 자체가 아닌 클래스
                    if issubclass(obj, BaseChunker) and obj is not BaseChunker:
                        try:
                            chunker_instance = obj()
                            self._register_user_chunker(
                                chunker_instance,
                                source=f"user:{py_file.name}"
                            )
                            chunker_classes_found += 1
                        except Exception as e:
                            logger.error(
                                f"Chunker 인스턴스 생성 실패 ({name} in {py_file.name}): {e}"
                            )

                if chunker_classes_found == 0:
                    logger.warning(
                        f"BaseChunker를 상속한 클래스를 찾을 수 없습니다: {py_file.name}"
                    )
                else:
                    logger.info(
                        f"사용자 chunker 로드 완료: {py_file.name} "
                        f"({chunker_classes_found}개 chunker)"
                    )

            except Exception as e:
                logger.error(f"Chunker 파일 로드 실패 ({py_file.name}): {e}")

    def _register_user_chunker(self, chunker: BaseChunker, source: str):
        """
        사용자 정의 chunker를 등록하고 충돌을 감지합니다.

        Args:
            chunker: 등록할 chunker 인스턴스
            source: chunker 출처 정보 (예: "user:header_chunker.py")
        """
        chunker_name = chunker.name

        # 기존 chunker가 있는지 확인
        if chunker_name in self._chunkers:
            old_source = self._chunker_sources.get(chunker_name, "unknown")
            logger.warning(
                f"Chunker 충돌: '{chunker_name}'는 이미 {old_source}에 의해 등록됨. "
                f"{source}:{chunker.__class__.__name__}으로 덮어씁니다."
            )

        # chunker 등록 (덮어쓰기)
        self._chunkers[chunker_name] = chunker
        self._chunker_sources[chunker_name] = f"{source}:{chunker.__class__.__name__}"

    def _load_chunker_config(self):
        """
        ConfigManager를 사용하여 chunker_config.yaml을 로드하고
        config에 정의된 파라미터로 chunker를 재생성합니다.
        """
        try:
            from maru_lang.configs import get_config_manager

            config_manager = get_config_manager()
            merged_config = config_manager.get_chunker_config()

            if not merged_config or not merged_config.chunkers:
                logger.debug("Chunker 설정이 없습니다.")
                return

            # config에 정의된 chunker들을 재생성 (파라미터 적용)
            for chunker_name, params in merged_config.chunkers.items():
                if chunker_name in self._chunkers:
                    # 기존 chunker를 config 파라미터로 재생성
                    old_chunker = self._chunkers[chunker_name]
                    chunker_class = old_chunker.__class__
                    try:
                        new_chunker = chunker_class(**params)
                        self._chunkers[chunker_name] = new_chunker
                        logger.info(
                            f"Chunker '{chunker_name}' config 적용: {params}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"Chunker '{chunker_name}' config 적용 실패: {e}"
                        )
                else:
                    logger.debug(f"알 수 없는 chunker: {chunker_name}")

            logger.info(
                f"Chunker config 로드 완료: {len(merged_config.chunkers)}개 chunker"
            )

        except ImportError as e:
            logger.warning(f"ConfigManager를 import할 수 없습니다: {e}")
        except Exception as e:
            logger.error(f"Chunker config 로드 실패: {e}")

    def register_chunker(self, chunker: BaseChunker, source: str = "custom"):
        """
        새로운 chunker를 등록합니다.

        Args:
            chunker: 등록할 chunker 인스턴스
            source: chunker 출처 정보
        """
        self._register_user_chunker(chunker, source)

    def get_chunker_by_name(self, name: str) -> Optional[BaseChunker]:
        """
        이름으로 chunker를 가져옵니다.

        Args:
            name: chunker 이름

        Returns:
            Optional[BaseChunker]: 해당 이름의 chunker, 없으면 None
        """
        return self._chunkers.get(name)

    def get_chunker_or_default(self, name: Optional[str] = None) -> BaseChunker:
        """
        이름으로 chunker를 가져오거나, 없으면 기본 chunker를 반환합니다.

        Args:
            name: chunker 이름 (None이면 기본값)

        Returns:
            BaseChunker: chunker 인스턴스
        """
        if name is None or name not in self._chunkers:
            # 기본 chunker (paragraph)
            return self._chunkers.get("paragraph", ParagraphChunker())

        return self._chunkers[name]

    def list_chunkers(self) -> Dict[str, str]:
        """
        등록된 모든 chunker의 목록을 반환합니다.

        Returns:
            Dict[str, str]: {chunker_name: description}
        """
        return {
            name: chunker.description
            for name, chunker in self._chunkers.items()
        }

    @property
    def default_chunker(self) -> BaseChunker:
        """기본 chunker (paragraph) - 편의를 위한 속성"""
        return self.get_chunker_or_default()


# 싱글톤 인스턴스
_chunker_instance: Optional[Chunker] = None


def get_chunker(
    user_chunkers_dir: Optional[Path] = None,
    force_new: bool = False,
) -> Chunker:
    """
    Chunker 싱글톤 인스턴스 반환

    Args:
        user_chunkers_dir: 사용자 정의 chunker 디렉토리 경로 (None이면 기본값)
        force_new: True면 기존 인스턴스 무시하고 새로 생성 (테스트용)

    Returns:
        Chunker: 싱글톤 인스턴스

    Example:
        >>> chunker_manager = get_chunker()
        >>> chunker = chunker_manager.get_chunker_by_name("paragraph")
    """
    global _chunker_instance

    if _chunker_instance is None or force_new:
        _chunker_instance = Chunker(user_chunkers_dir=user_chunkers_dir)

    return _chunker_instance


__all__ = [
    "BaseChunker",
    "ParagraphChunker",
    "FixedSizeChunker",
    "SentenceChunker",
    "Chunker",
    "get_chunker",
]
