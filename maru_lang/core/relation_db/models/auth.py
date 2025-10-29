from __future__ import annotations
import datetime
from tortoise.models import Model
from tortoise import fields


class User(Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255, index=True, null=True)
    email = fields.CharField(max_length=255, index=True, unique=True)
    role = fields.ForeignKeyField(
        "models.UserRole", related_name="users", null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "user"


class UserGroup(Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255, unique=True)

    class Meta:
        table = "user_group"


class UserGroupMembership(Model):
    user = fields.ForeignKeyField(
        "models.User",
        related_name="group_memberships")
    group = fields.ForeignKeyField(
        "models.UserGroup",
        related_name="members")

    class Meta:
        table = "user_group_membership"


class UserGroupInclusion(Model):
    parent = fields.ForeignKeyField(
        "models.UserGroup", related_name="includes")  # 상위 그룹
    child = fields.ForeignKeyField(
        "models.UserGroup", related_name="included_by")  # 하위 그룹

    class Meta:
        table = "user_group_inclusion"


class OTP(Model):
    id = fields.IntField(pk=True)
    email = fields.CharField(max_length=255, index=True)
    code = fields.CharField(max_length=6)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "otp"

    async def is_valid(self):
        """ 인증코드가 5분 이내인지 확인 """
        expiration_time = self.created_at + datetime.timedelta(minutes=5)
        return expiration_time > datetime.datetime.now(datetime.timezone.utc)


class UserToken(Model):
    id = fields.IntField(pk=True)
    user_id = fields.CharField(max_length=255, index=True)  # 사용자 고유 ID
    device_id = fields.CharField(max_length=255, index=True)  # 기기 고유 ID
    jwt_token = fields.TextField()  # JWT 토큰
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "user_token"


class RefreshToken(Model):
    id = fields.IntField(pk=True)
    user_id = fields.CharField(max_length=255, index=True)
    device_id = fields.CharField(max_length=255, index=True)
    refresh_token = fields.TextField()  # 발급된 Refresh Token 문자열
    created_at = fields.DatetimeField(auto_now_add=True)
    expires_at = fields.DatetimeField()

    class Meta:
        table = "refresh_token"


class UserRole(Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255, index=True, unique=True)
    description = fields.TextField(null=True)

    class Meta:
        table = "user_role"
