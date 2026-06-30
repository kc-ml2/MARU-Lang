"""Chat-related enums."""
from enum import IntEnum


class SessionStatus(IntEnum):
    ACTIVE   = 1   # Open, accepting messages
    ARCHIVED = 2   # Closed by the user
    DELETED  = 3   # Soft-deleted


class UserMemoryKind(IntEnum):
    FACT       = 1   # 사용자 사실 (예: 이름=김지훈)
    PREFERENCE = 2   # 사용자 선호 (예: 짧은 말투)


class CanvasStatus(IntEnum):
    """문서 작성(doc) 그래프의 canvas 상태."""
    DRAFTING  = 1   # 초기 그라운딩/초안 생성 중
    EDITING   = 2   # 최소 1회 편집 사이클 진행
    FINALIZED = 3   # 사용자 확정 — 잠금
