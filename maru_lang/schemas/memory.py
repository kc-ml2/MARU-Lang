"""User memory API schemas."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class MemoryResponse(BaseModel):
    id: int
    kind: int           # UserMemoryKind value (1=FACT, 2=PREFERENCE)
    key: Optional[str] = None
    content: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
