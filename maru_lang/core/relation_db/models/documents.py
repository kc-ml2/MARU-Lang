from tortoise.models import Model
from tortoise import fields
from maru_lang.enums.documents import (
    PermissionAction,
    DocumentStatus,
)


class Document(Model):
    id = fields.CharField(pk=True, max_length=64)  # ULID/UUIDv7 권장
    name = fields.CharField(max_length=255, index=True)

    file_path = fields.CharField(max_length=500, null=True)
    file_size = fields.BigIntField(null=True)
    head_hash = fields.CharField(
        max_length=64, null=True, index=True)   # blake3(앞 64KB)
    full_hash = fields.CharField(
        max_length=64, null=True, index=True)   # blake3(전체: 지연 계산 가능)
    source_fingerprint = fields.CharField(
        max_length=64, unique=True, null=True)  # 업서트 기준 키

    metadata = fields.JSONField(default=dict)
    status = fields.IntEnumField(
        DocumentStatus, default=DocumentStatus.PROCESSING)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "document"
        indexes = [["name", "file_size", "head_hash"]]


class DocumentGroup(Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255)
    base_path = fields.CharField(
        max_length=500,
        unique=True,  # 같은 파일시스템 경로는 단일 DocumentGroup만 존재
    )
    embedder = fields.CharField(
        max_length=255,
    )
    minhash_signature = fields.JSONField(null=True) # MinHash 시그니처 (128개 정수 배열)
    signature_updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "document_group"


class DocumentGroupMembership(Model):
    document = fields.ForeignKeyField(
        "models.Document",
        related_name="group_memberships",
        on_delete=fields.CASCADE)
    group = fields.ForeignKeyField(
        "models.DocumentGroup",
        related_name="documents",
        on_delete=fields.CASCADE)

    class Meta:
        table = "document_group_membership"


class DocumentGroupInclusion(Model):
    parent = fields.ForeignKeyField(
        "models.DocumentGroup",
        related_name="includes",
        on_delete=fields.CASCADE)
    child = fields.ForeignKeyField(
        "models.DocumentGroup",
        related_name="included_by",
        on_delete=fields.CASCADE)

    class Meta:
        table = "document_group_inclusion"
        unique_together = ("parent", "child")


# 그룹 ↔ 문서그룹 권한
class GroupPermission(Model):
    user_group = fields.ForeignKeyField(
        "models.UserGroup",
        related_name="permissions",
        on_delete=fields.CASCADE)
    document_group = fields.ForeignKeyField(
        "models.DocumentGroup",
        related_name="permissions",
        on_delete=fields.CASCADE)
    action = fields.CharEnumField(PermissionAction)

    class Meta:
        table = "group_permission"
        unique_together = (("user_group", "document_group", "action"),)