"""HTTP contracts for inspecting and controlling the stable pipeline."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from maru_lang.enums import PipelineStage


class PipelineConfigPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parser: str = "auto"
    chunker: str = "structure"
    target_tokens: int = Field(default=800, ge=200, le=2_000)
    overlap_tokens: int = Field(default=80, ge=0)
    embedding_model: str = "multilingual-default"


class PipelineInspectionResponse(BaseModel):
    storage_id: str
    stages: list[str]
    config: PipelineConfigPayload
    config_hash: str
    latest_run_id: str | None
    latest_run_status: str | None
    configured: bool


class RerunPipelineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_stage: PipelineStage = PipelineStage.SCAN


class PipelineRunResponse(BaseModel):
    id: str
    storage_id: str
    from_stage: str
    status: str
    config_snapshot: PipelineConfigPayload
    config_hash: str
    report: dict[str, object] | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
