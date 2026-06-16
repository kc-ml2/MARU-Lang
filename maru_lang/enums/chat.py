"""Chat-related enums."""
from enum import IntEnum


class SessionStatus(IntEnum):
    ACTIVE   = 1   # Open, accepting messages
    ARCHIVED = 2   # Closed by the user
    DELETED  = 3   # Soft-deleted


class UserMemoryKind(IntEnum):
    FACT       = 1   # 사용자 사실 (예: 이름=김지훈)
    PREFERENCE = 2   # 사용자 선호 (예: 짧은 말투)
