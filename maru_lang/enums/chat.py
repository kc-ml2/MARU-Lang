"""Chat-related enums."""
from enum import IntEnum


class SessionStatus(IntEnum):
    ACTIVE   = 1   # Open, accepting messages
    ARCHIVED = 2   # Closed by the user
    DELETED  = 3   # Soft-deleted
