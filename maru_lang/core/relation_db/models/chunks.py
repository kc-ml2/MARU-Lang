"""Backend-neutral retrieval chunk metadata."""
from tortoise import fields
from tortoise.models import Model


class DocumentChunk(Model):
    """Optional local chunk metadata, independent of embedding technology."""

    id = fields.CharField(pk=True, max_length=128)
    document = fields.ForeignKeyField(
        "models.Document", related_name="chunks", on_delete=fields.CASCADE
    )
    content = fields.TextField()
    metadata = fields.JSONField(default=dict)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:  # type: ignore[override]
        table = "document_chunk"
        indexes = (("document_id",),)
