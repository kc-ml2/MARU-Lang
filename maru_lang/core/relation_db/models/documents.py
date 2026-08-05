"""Document, DocumentGroup, and DocumentAuditLog models."""
from tortoise.models import Model
from tortoise import fields
from maru_lang.enums.documents import DocumentStatus, AuditAction, DocumentSourceStatus


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


class DocumentAuditLog(Model):
    id = fields.IntField(pk=True)
    document_id = fields.CharField(max_length=64, null=True, index=True)
    document_name = fields.CharField(max_length=255)
    team_id = fields.IntField(index=True)
    user = fields.ForeignKeyField(
        "models.User", null=True, on_delete=fields.SET_NULL, related_name="audit_logs",
    )
    action = fields.IntEnumField(AuditAction)
    detail = fields.JSONField(default=dict)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:  # type: ignore
        table = "document_audit_log"
        ordering = ["-created_at"]


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


class DocumentSource(Model):
    """Server-managed file source (e.g. /data/readme/) that can be connected to teams."""
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255, index=True)
    description = fields.TextField(null=True)
    source_path = fields.CharField(max_length=500, unique=True, index=True)
    file_pattern = fields.CharField(max_length=255, null=True)  # optional glob pattern
    status = fields.IntEnumField(
        DocumentSourceStatus, default=DocumentSourceStatus.CONNECTED,
    )

    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:  # type: ignore
        table = "document_source"


class SourceTeamLink(Model):
    """N:N link between DocumentSource and Team."""
    id = fields.IntField(pk=True)
    source = fields.ForeignKeyField(
        "models.DocumentSource",
        related_name="team_links",
        on_delete=fields.CASCADE,
        index=True,
    )
    team = fields.ForeignKeyField(
        "models.Team",
        related_name="source_links",
        on_delete=fields.CASCADE,
        index=True,
    )
    # The root DocumentGroup that mirrors this source's top-level structure
    root_group = fields.ForeignKeyField(
        "models.DocumentGroup",
        null=True,
        on_delete=fields.SET_NULL,
        unique=True,  # 1:1 between DocumentSource and its root DocumentGroup
    )

    class Meta:  # type: ignore
        table = "source_team_link"
        unique_together = (("source", "team"))
