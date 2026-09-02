"""Stable role values persisted by MARU."""
from enum import StrEnum


class StorageOwnerType(StrEnum):
    TEAM = "team"
    SYSTEM = "system"


class TeamRole(StrEnum):
    MEMBER = "member"
    ADMIN = "admin"


class PipelineStage(StrEnum):
    SCAN = "scan"
    PARSE = "parse"
    CHUNK = "chunk"
    EMBED = "embed"
    INDEX = "index"


class PipelineRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
