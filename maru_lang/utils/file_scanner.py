"""
파일 스캔 유틸리티

CLI와 API에서 공통으로 사용할 파일 스캔 기능
"""
from pathlib import Path
from typing import List
from maru_lang.pluggable.loaders import Loader

def scan_directory(path: Path, recursive: bool = True) -> List[Path]:
    """
    디렉토리 스캔하여 모든 파일 리스트 반환

    Args:
        path: 스캔할 디렉토리 경로
        recursive: True이면 하위 디렉토리도 재귀적으로 스캔

    Returns:
        파일 Path 객체 리스트 (정렬됨)

    Raises:
        ValueError: path가 존재하지 않거나 디렉토리가 아닌 경우
    """
    if not path.exists():
        raise ValueError(f"Path does not exist: {path}")

    if not path.is_dir():
        raise ValueError(f"Path is not a directory: {path}")

    if recursive:
        files = sorted([f for f in path.rglob("*") if f.is_file()])
    else:
        files = sorted([f for f in path.glob("*") if f.is_file()])

    return files


def filter_supported_files(files: List[Path], loader_manager: Loader) -> tuple[List[Path], List[Path]]:
    """
    파일 리스트에서 지원되는 파일과 지원되지 않는 파일 분리

    Args:
        files: 필터링할 파일 리스트
        loader_manager: LoaderManager 인스턴스

    Returns:
        (supported_files, unsupported_files) 튜플
    """
    supported = []
    unsupported = []

    for file_path in files:
        if loader_manager.supports(file_path):
            supported.append(file_path)
        else:
            unsupported.append(file_path)

    return supported, unsupported
