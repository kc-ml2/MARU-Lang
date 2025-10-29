"""
Reranker Components

임베딩 모델 기반 reranker 또는 LLM 기반 reranker agent를 정의할 수 있습니다.

## 사용 방법

### Model 기반 (기본값)
configs/reranker_config.yaml:
    enabled: true
    method: model
    default_model: BAAI/bge-reranker-v2-m3

### Agent 기반 (LLM)
1. rerankers/my_reranker.py 생성 (BaseAgent 구현)
2. configs/agent_config.yaml에 등록
3. configs/reranker_config.yaml 설정:
    enabled: true
    method: agent
    agent_name: my_reranker
"""

__all__ = []
