"""
Reranker configuration models
"""
from dataclasses import dataclass
from typing import Optional, Literal


@dataclass
class RerankerConfig:
    """Reranker configuration - reranker 모델 및 사용 여부 설정"""
    enabled: bool = True
    method: Literal["model", "agent"] = "model"

    # Method: "model" - 임베딩 모델 기반 reranking
    default_model: str = "BAAI/bge-reranker-v2-m3"

    # Method: "agent" - Agent 기반 reranking (LLM 등)
    agent_name: Optional[str] = None

    source_path: str = ""
    is_override: bool = False
