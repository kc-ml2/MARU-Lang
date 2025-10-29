"""
Reranker configuration models
"""
from dataclasses import dataclass, field
from typing import List, Optional, Literal


@dataclass
class ModelInfo:
    """Reranker 모델 정보"""
    name: str
    description: str = ""


@dataclass
class RerankerConfig:
    """Reranker configuration - reranker 모델 및 사용 여부 설정"""
    enabled: bool = True
    method: Literal["model", "agent"] = "model"

    # Method: "model" - 임베딩 모델 기반 reranking
    default_model: str = "BAAI/bge-reranker-v2-m3"
    models: List[ModelInfo] = field(default_factory=list)

    # Method: "agent" - Agent 기반 reranking (LLM 등)
    agent_name: Optional[str] = None

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
