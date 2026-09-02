"""Minimal execution history for MARU's fixed indexing pipeline."""
from tortoise import fields
from tortoise.models import Model

from maru_lang.enums import PipelineRunStatus, PipelineStage


class PipelineRun(Model):
    id = fields.CharField(pk=True, max_length=64)
    storage = fields.ForeignKeyField(
        "models.SourceStorage",
        related_name="pipeline_runs",
        on_delete=fields.CASCADE,
        index=True,
    )
    requested_by = fields.ForeignKeyField(
        "models.User",
        related_name="pipeline_runs",
        null=True,
        on_delete=fields.SET_NULL,
    )
    from_stage = fields.CharEnumField(PipelineStage)
    status = fields.CharEnumField(PipelineRunStatus, index=True)
    config_snapshot = fields.JSONField(default=dict)
    report = fields.JSONField(null=True)
    error = fields.TextField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    completed_at = fields.DatetimeField(null=True)

    class Meta:  # type: ignore[override]
        table = "pipeline_run"
        indexes = (("storage_id", "created_at"),)
