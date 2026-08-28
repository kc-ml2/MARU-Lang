"""Stable role values persisted by MARU."""
from enum import StrEnum


class TeamRole(StrEnum):
    MEMBER = "member"
    ADMIN = "admin"
