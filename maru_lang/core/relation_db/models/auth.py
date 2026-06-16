from __future__ import annotations
from tortoise.models import Model
from tortoise import fields


class User(Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255, index=True, null=True)
    email = fields.CharField(max_length=255, index=True, unique=True)
    role = fields.ForeignKeyField(
        "models.UserRole", related_name="users", null=True)
    created_at = fields.DatetimeField(auto_now_add=True)


class UserRole(Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255, index=True, unique=True)
    description = fields.TextField(null=True)


class Team(Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255, unique=True)
    manager = fields.ForeignKeyField(
        "models.User",
        related_name="managed_teams",
        on_delete=fields.RESTRICT  # Prevents User deletion if managing Teams
    )
    is_private = fields.BooleanField(default=False)
    allowed_graphs = fields.JSONField(default=list)  # graph ids; empty = all registered
    created_at = fields.DatetimeField(auto_now_add=True)


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
    role = fields.CharField(max_length=50, default="member")
    joined_at = fields.DatetimeField(auto_now_add=True)

    class Meta:  # type: ignore[override]
        unique_together = (("user", "team"),)


class EmailVerificationCode(Model):
    id = fields.IntField(pk=True)
    email = fields.CharField(max_length=255, index=True)
    code = fields.CharField(max_length=6)
    created_at = fields.DatetimeField(auto_now_add=True)


class UserToken(Model):
    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField(
        "models.User",
        related_name="user_tokens",
        on_delete=fields.CASCADE,
        index=True)

    device_id = fields.CharField(max_length=255, index=True)  # a.k.a client_id
    token_hash = fields.CharField(max_length=64, unique=True, index=True)

    created_at = fields.DatetimeField(auto_now_add=True)
    expires_at = fields.DatetimeField(index=True)
    revoked_at = fields.DatetimeField(null=True, index=True)


class RefreshToken(Model):
    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField(
        "models.User",
        related_name="refresh_tokens",
        on_delete=fields.CASCADE,
        index=True)

    device_id = fields.CharField(max_length=255, index=True)  # a.k.a client_id
    token_hash = fields.CharField(max_length=64, unique=True, index=True)

    created_at = fields.DatetimeField(auto_now_add=True)
    expires_at = fields.DatetimeField(index=True)

    revoked_at = fields.DatetimeField(null=True, index=True)
    rotated_at = fields.DatetimeField(null=True, index=True)

    replaced_by = fields.ForeignKeyField(
        "models.RefreshToken",
        related_name="replaces",
        null=True,
        on_delete=fields.SET_NULL
    )


class UserChatToken(Model):
    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField(
        "models.User",
        related_name="chat_tokens",
        on_delete=fields.CASCADE,
        index=True)
    token_hash = fields.CharField(max_length=64, unique=True, index=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    expires_at = fields.DatetimeField(index=True)
    used_at = fields.DatetimeField(null=True, index=True)
    revoked_at = fields.DatetimeField(null=True, index=True)
