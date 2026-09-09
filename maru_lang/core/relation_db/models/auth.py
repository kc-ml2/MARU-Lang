from __future__ import annotations
from tortoise.models import Model
from tortoise import fields
from tortoise.indexes import PartialIndex

from maru_lang.enums import TeamRole


class User(Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255, index=True, null=True)
    email = fields.CharField(max_length=255, index=True, unique=True)
    created_at = fields.DatetimeField(auto_now_add=True)


class Team(Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255, unique=True)
    description = fields.TextField(null=True)
    manager = fields.ForeignKeyField(
        "models.User",
        related_name="managed_teams",
        on_delete=fields.RESTRICT  # Prevents User deletion if managing Teams
    )
    is_personal = fields.BooleanField(default=False, index=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:  # type: ignore[override]
        indexes = (
            PartialIndex(
                fields=("manager_id",),
                name="uidx_team_personal_manager",
                condition={"is_personal": True},
            ),
        )


class TeamMember(Model):
    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField(
        "models.User",
        related_name="team_memberships",
        on_delete=fields.CASCADE
    )
    team = fields.ForeignKeyField(
        "models.Team",
        related_name="members",
        on_delete=fields.CASCADE
    )
    role = fields.CharEnumField(TeamRole, default=TeamRole.MEMBER)
    joined_at = fields.DatetimeField(auto_now_add=True)

    class Meta:  # type: ignore[override]
        unique_together = (("user", "team"),)


class ApiToken(Model):
    """Operator-issued opaque credential; plaintext is never persisted."""

    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField(
        "models.User", related_name="api_tokens", on_delete=fields.CASCADE
    )
    token_hash = fields.CharField(max_length=64, unique=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    expires_at = fields.DatetimeField(null=True)
    revoked_at = fields.DatetimeField(null=True)
