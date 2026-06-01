from tortoise.models import Model
from tortoise import fields
from maru_lang.enums.chat import SessionStatus


class Session(Model):
    """A chat session = one LangGraph thread (id == thread_id)."""
    id = fields.CharField(pk=True, max_length=64)  # uuid4().hex, used as thread_id
    user = fields.ForeignKeyField(
        "models.User",
        related_name="sessions",
        on_delete=fields.CASCADE,
        index=True,
    )
    title = fields.CharField(max_length=255, null=True)
    status = fields.IntEnumField(SessionStatus, default=SessionStatus.ACTIVE)
    summary = fields.TextField(null=True)  # 세션 누적(롤링) 요약 - 매 턴 갱신, 컨텍스트 로딩용
    metadata = fields.JSONField(default=dict)  # function 모드 등 세션 설정
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:  # type: ignore
        table = "session"
        ordering = ["-updated_at"]


class Conversation(Model):
    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField(
        "models.User", related_name="conversations", on_delete=fields.OnDelete.CASCADE)
    session = fields.ForeignKeyField(
        "models.Session",
        related_name="conversations",
        on_delete=fields.CASCADE,
        null=True,
        index=True,
    )
    question = fields.TextField()  # 사용자 질문
    enhanced_question = fields.TextField(null=True)  # 확장된 질문
    answer = fields.TextField()    # AI 답변
    summary = fields.TextField(null=True)  # 이 턴(질문+답변)의 요약 - 나중에 채움
    metadata = fields.JSONField(default=dict)  # API 호출 정보, 토큰 수, 처리 시간 등
    feedback_score = fields.IntField(null=True)   # 사용자 피드백 점수 (예: 1-5)
    feedback_reason = fields.TextField(null=True)  # 피드백 사유
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
