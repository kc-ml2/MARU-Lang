from tortoise.models import Model
from tortoise import fields
from datetime import datetime, timezone
from enum import IntEnum


class Conversation(Model):
    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField(
        "models.User", related_name="conversations", on_delete=fields.OnDelete.CASCADE)
    question = fields.TextField()  # 사용자 질문
    enhanced_question = fields.TextField(null=True)  # 확장된 질문
    answer = fields.TextField()    # AI 답변
    metadata = fields.JSONField(default={})  # API 호출 정보, 토큰 수, 처리 시간 등
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "conversation"


class ConversationReference(Model):
    id = fields.IntField(pk=True)
    conversation = fields.ForeignKeyField(
        "models.Conversation",
        related_name="references",
        on_delete=fields.OnDelete.CASCADE)
    document = fields.ForeignKeyField(
        "models.Document",
        related_name="conversation_references",
        on_delete=fields.OnDelete.CASCADE)
    score = fields.FloatField()  # 검색 관련성 점수

    class Meta:
        table = "conversation_reference"
