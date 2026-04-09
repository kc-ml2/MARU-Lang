"""Document-related enums."""
from enum import IntEnum


class DocumentStatus(IntEnum):
    UPLOADING  = 1   # File saved, waiting for processing
    PROCESSING = 2   # Parsing / chunking / embedding in progress
    ACTIVE     = 3   # Embedding complete, searchable
    ERROR      = 4   # Processing failed
    INACTIVE   = 5   # Disabled (not searchable)


class AuditAction(IntEnum):
    UPLOAD         = 1
    RE_UPLOAD      = 2
    DELETE         = 3
    INGEST_SUCCESS = 4
    INGEST_ERROR   = 5
