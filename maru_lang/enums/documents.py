"""Document status enum."""
from enum import IntEnum


class DocumentStatus(IntEnum):
    UPLOADING  = 1   # File saved, waiting for processing
    PROCESSING = 2   # Parsing / chunking / embedding in progress
    ACTIVE     = 3   # Embedding complete, searchable
    ERROR      = 4   # Processing failed
    INACTIVE   = 5   # Disabled (not searchable)
