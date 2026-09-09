"""Storage-centric filesystem document models."""
from tortoise import fields
from tortoise.models import Model

from maru_lang.enums import StorageOwnerType


class SourceStorage(Model):
    """A physical source tree owned by a team or by the MARU system."""

    id = fields.CharField(primary_key=True, max_length=64)
    name = fields.CharField(max_length=255)
    owner_type = fields.CharEnumField(StorageOwnerType, db_index=True)
    storage_type = fields.CharField(max_length=16, default="managed")
    external_path = fields.TextField(null=True)
    owner_team = fields.ForeignKeyField(
        "models.Team",
        related_name="owned_source_storages",
        null=True,
        on_delete=fields.RESTRICT,
        db_index=True,
    )
    system_key = fields.CharField(max_length=100, null=True, unique=True)
    auto_attach = fields.BooleanField(default=False, db_index=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:  # type: ignore[override]
        table = "source_storage"


class TeamStorageLink(Model):
    """Grant a team access to a source storage without duplicating documents."""

    id = fields.IntField(primary_key=True)
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
