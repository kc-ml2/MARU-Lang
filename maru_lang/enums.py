"""Stable role values persisted by MARU."""
from enum import StrEnum


class StorageOwnerType(StrEnum):
    TEAM = "team"
    SYSTEM = "system"


class TeamRole(StrEnum):
    MEMBER = "member"
    ADMIN = "admin"
