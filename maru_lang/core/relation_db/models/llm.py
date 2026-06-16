from tortoise.models import Model
from tortoise import fields


class Llm(Model):
    """Config LLM의 DB 미러.

    `maru_config.yaml`의 `llms:` 목록이 진실 원천이고, 이 테이블은 그 미러본이다
    (startup마다 `sync_llms_from_config`로 동기화). User/Conversation이 FK로
    가리킬 수 있게 하려는 목적. config에서 LLM이 빠져도 row는 삭제하지 않고
    `enabled=False`로만 두어, 과거 `Conversation.llm_used` FK가 깨지지 않게 한다.
    """
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255, unique=True, index=True)  # config 자연키
    provider = fields.CharField(max_length=64)
    model_name = fields.CharField(max_length=255)
    enabled = fields.BooleanField(default=True)   # config enabled 미러 + soft-disable
    weight = fields.IntField(default=1)           # 가입 밸런싱 목표 비율
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:  # type: ignore[override]
        table = "llm"
