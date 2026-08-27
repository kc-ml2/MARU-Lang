from tortoise.models import Model
from tortoise import fields


class Llm(Model):
    """Config LLM의 DB 미러.

    `maru_config.yaml`의 `llms:` 목록이 진실 원천이고, 이 테이블은 대화 감사
    기록을 위한 미러다. config에서 LLM이 빠져도 row는 삭제하지 않고
    `enabled=False`로 두어 과거 `Conversation.llm_used` FK를 보존한다.
    """
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255, unique=True, index=True)  # config 자연키
    provider = fields.CharField(max_length=64)
    model_name = fields.CharField(max_length=255)
    enabled = fields.BooleanField(default=True)   # config enabled 미러 + soft-disable
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:  # type: ignore[override]
        table = "llm"
