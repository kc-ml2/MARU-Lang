"""Config API schemas."""
from pydantic import BaseModel


class ConfigResponse(BaseModel):
    supported_extensions: list[str]
