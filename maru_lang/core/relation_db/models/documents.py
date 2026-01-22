from tortoise.models import Model
from tortoise import fields
from maru_lang.enums.documents import DocumentStatus


class Document(Model):
    id = fields.CharField(pk=True, max_length=64)  # ULID/UUIDv7 권장
    name = fields.CharField(max_length=255, index=True)
    group = fields.ForeignKeyField(
        "models.DocumentGroup",
        related_name="documents",
        on_delete=fields.CASCADE,
        index=True)

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
    rag_components = fields.JSONField(null=True, default=dict)  # 사용된 설정의 스냅샷

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
        index=True)
    parent = fields.ForeignKeyField(
        "models.DocumentGroup",
        related_name="children",
        null=True,  # 루트는 null
        on_delete=fields.CASCADE)
    rag_components = fields.JSONField(null=True, default=dict)

    class Meta:  # type: ignore
        table = "document_group"
