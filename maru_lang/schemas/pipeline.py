"""HTTP contracts for MARU's minimal fixed pipeline."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from maru_lang.enums import PipelineStage


class PipelineConfigPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_tokens: int = Field(default=800, ge=200, le=2_000)
    overlap_tokens: int = Field(default=80, ge=0)

    @model_validator(mode="after")
    def validate_overlap(self) -> "PipelineConfigPayload":
        if self.overlap_tokens > self.target_tokens // 4:
            raise ValueError("overlap_tokens must not exceed 25% of target_tokens")
        return self


class PipelineInspectionResponse(BaseModel):
    storage_id: str
    stages: list[str]
    config: PipelineConfigPayload
    latest_run_id: str | None
    latest_run_status: str | None


class RerunPipelineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_stage: PipelineStage = PipelineStage.SCAN


class PipelineRunResponse(BaseModel):
    id: str
    storage_id: str
    from_stage: str
    status: str
    config_snapshot: PipelineConfigPayload
    report: dict[str, object] | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None
