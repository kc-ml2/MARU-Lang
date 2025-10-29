"""
Chunker configuration models
"""
from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class ChunkerConfig:
    """
    Chunker configuration

    각 chunker의 생성자 파라미터를 설정
    """
    # chunker 이름 -> 생성자 파라미터 매핑
    # 예: {"paragraph": {"max_chunk_size": 500}}
    chunkers: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Configuration metadata
    source_path: str = ""
    is_override: bool = False
