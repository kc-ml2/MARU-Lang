"""
Embedder configuration models
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class EmbedderConfig:
    """
    Embedder configuration

    임베딩 모델 및 디바이스 설정
    """
    # 기본 임베딩 모델 (모든 document group의 기본값)
    # rag_config.yaml에서 그룹별로 override 가능
    default_model: str = "BAAI/bge-m3"

    # 디바이스 (None이면 자동 선택: cuda > mps > cpu)
    device: Optional[str] = None

    # Configuration metadata
    source_path: str = ""
    is_override: bool = False
