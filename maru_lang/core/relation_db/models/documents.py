"""Document and DocumentGroup models."""
from tortoise.models import Model
from tortoise import fields
from maru_lang.enums.documents import DocumentStatus


class Document(Model):
    id = fields.CharField(pk=True, max_length=64)
    name = fields.CharField(max_length=255, index=True)
    group = fields.ForeignKeyField(
        "models.DocumentGroup",
        related_name="documents",
        on_delete=fields.CASCADE,
        index=True,
    )

    file_path = fields.CharField(max_length=500, null=True)
    storage_path = fields.CharField(max_length=500, null=True)  # permanent local copy
    file_size = fields.BigIntField(null=True)
    head_hash = fields.CharField(max_length=64, null=True, index=True)
    full_hash = fields.CharField(max_length=64, null=True, index=True)
    source_fingerprint = fields.CharField(max_length=64, unique=True, null=True)

    metadata = fields.JSONField(default=dict)
    status = fields.IntEnumField(DocumentStatus, default=DocumentStatus.UPLOADING)
    error_message = fields.TextField(null=True)

    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:  # type: ignore
        table = "document"
        indexes = [["name", "file_size", "head_hash"]]


class DocumentGroup(Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255, index=True)
    description = fields.TextField(null=True)
    team = fields.ForeignKeyField(
        "models.Team",
        related_name="document_groups",
        on_delete=fields.CASCADE,
        index=True,
    )
    parent = fields.ForeignKeyField(
        "models.DocumentGroup",
        related_name="children",
        null=True,
        on_delete=fields.CASCADE,
    )

    class Meta:  # type: ignore
        table = "document_group"
