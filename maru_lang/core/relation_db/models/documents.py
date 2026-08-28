"""Filesystem source and document projection models."""
from tortoise.models import Model
from tortoise import fields

from maru_lang.enums import StorageOwnerType


class SourceStorage(Model):
    """A physical source folder that can be connected to multiple teams."""
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

    class Meta:  # type: ignore
        table = "source_storage"


class TeamStorageLink(Model):
    """Grant a team read access to a source storage.

    Only ``SourceStorage.owner_team`` may mutate files; every linked team gets
    its own Document/chunk projection for existing team-scoped retrieval.
    """
    id = fields.IntField(pk=True)
    team = fields.ForeignKeyField(
        "models.Team", related_name="source_storage_links", on_delete=fields.CASCADE
    )
    storage = fields.ForeignKeyField(
        "models.SourceStorage", related_name="team_links", on_delete=fields.CASCADE
    )
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:  # type: ignore
        table = "team_storage_link"
        unique_together = (("team", "storage"),)


class Document(Model):
    id = fields.CharField(pk=True, max_length=64)
    name = fields.CharField(max_length=255, index=True)
    group = fields.ForeignKeyField(
        "models.DocumentGroup",
        related_name="documents",
        on_delete=fields.CASCADE,
        index=True,
    )

    storage = fields.ForeignKeyField(
        "models.SourceStorage",
        related_name="documents",
        null=True,
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
