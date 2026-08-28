"""Stable role values persisted by MARU."""
from enum import StrEnum


class AccountRole(StrEnum):
    ANONYMOUS = "anonymous"
    EDITOR = "editor"
    ADMIN = "admin"


class TeamRole(StrEnum):
    PENDING = "pending"
    MEMBER = "member"
    ADMIN = "admin"
