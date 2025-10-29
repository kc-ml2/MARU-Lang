"""
Embedder configuration models
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class ModelInfo:
    """임베딩 모델 정보"""
    name: str
    dimension: int
    description: str = ""


@dataclass
class EmbedderConfig:
    """
    Embedder configuration

    임베딩 모델 및 디바이스 설정
    """
    # 기본 임베딩 모델
    default_model: str = "BAAI/bge-m3"

    # 디바이스 (None이면 자동 선택: cuda > mps > cpu)
    device: Optional[str] = None

    # 사용 가능한 모델 목록 (선택사항)
    models: List[ModelInfo] = field(default_factory=list)

    # Configuration metadata
    source_path: str = ""
    is_override: bool = False

    def __post_init__(self):
        """Post-process configuration"""
        # models를 dict에서 ModelInfo로 변환
        new_models = []
        for model in self.models:
            if isinstance(model, dict):
                new_models.append(ModelInfo(**model))
            else:
                new_models.append(model)
        self.models = new_models
