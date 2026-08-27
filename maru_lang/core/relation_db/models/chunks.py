"""PostgreSQL pgvector-backed retrieval chunks."""
from tortoise import fields
from tortoise.models import Model


class DocumentChunk(Model):
    """Text chunk metadata.

    The embedding column is managed by the pgvector repository/migration once
    the embedding dimension is chosen. Keeping it out of the ORM avoids baking
    a model-specific dimension into the application settings.
    """

    id = fields.CharField(pk=True, max_length=128)
    document = fields.ForeignKeyField(
        "models.Document", related_name="chunks", on_delete=fields.CASCADE
    )
    team_id = fields.BigIntField(index=True)
    content = fields.TextField()
    metadata = fields.JSONField(default=dict)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:  # type: ignore[override]
        table = "document_chunk"
        indexes = (("team_id", "document_id"),)
