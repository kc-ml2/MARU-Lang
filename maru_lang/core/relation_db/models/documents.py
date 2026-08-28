"""Storage-centric filesystem document models."""
from tortoise import fields
from tortoise.models import Model

from maru_lang.enums import StorageOwnerType


class SourceStorage(Model):
    """A physical source tree owned by a team or by the MARU system."""

    id = fields.CharField(pk=True, max_length=64)
    name = fields.CharField(max_length=255)
    owner_type = fields.CharEnumField(StorageOwnerType, index=True)
    owner_team = fields.ForeignKeyField(
        "models.Team",
        related_name="owned_source_storages",
        null=True,
        on_delete=fields.RESTRICT,
        index=True,
    )
    system_key = fields.CharField(max_length=100, null=True, unique=True)
    auto_attach = fields.BooleanField(default=False, index=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:  # type: ignore[override]
        table = "source_storage"


class TeamStorageLink(Model):
    """Grant a team access to a source storage without duplicating documents."""

    id = fields.IntField(pk=True)
    team = fields.ForeignKeyField(
        "models.Team", related_name="source_storage_links", on_delete=fields.CASCADE
    )
    storage = fields.ForeignKeyField(
        "models.SourceStorage", related_name="team_links", on_delete=fields.CASCADE
    )
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:  # type: ignore[override]
        table = "team_storage_link"
        unique_together = (("team", "storage"),)


class Document(Model):
    """One file in a storage, identified by its normalized relative path."""

    id = fields.CharField(pk=True, max_length=64)
    storage = fields.ForeignKeyField(
        "models.SourceStorage",
        related_name="documents",
        on_delete=fields.CASCADE,
        index=True,
    )
    relative_path = fields.CharField(max_length=1024)
    name = fields.CharField(max_length=255, index=True)
    file_size = fields.BigIntField(null=True)
    modified_at_ns = fields.BigIntField(null=True)
    content_hash = fields.CharField(max_length=64, null=True, index=True)
    metadata = fields.JSONField(default=dict)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:  # type: ignore[override]
        table = "document"
        unique_together = (("storage", "relative_path"),)
        indexes = (("storage_id", "relative_path"),)
