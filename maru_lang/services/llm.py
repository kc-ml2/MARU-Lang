"""Mirror configured LLM metadata for immutable conversation audit records."""
import logging

from maru_lang.configs import get_config
from maru_lang.core.relation_db.models.llm import Llm

logger = logging.getLogger(__name__)


async def sync_llms_from_config() -> None:
    """config의 LLM 목록을 DB `Llm` 테이블에 미러링한다.

    - config에 있는 LLM은 `name` 기준 upsert한다.
    - config에서 사라진 LLM은 삭제하지 않고 비활성화하여 과거
      `Conversation.llm_used` FK를 보존한다.
    """
    cfg = get_config()
    config_names: set[str] = set()

    for lc in cfg.llms:
        config_names.add(lc.name)
        await Llm.update_or_create(
            name=lc.name,
            defaults={
                "provider": lc.provider,
                "model_name": lc.model_name,
                "enabled": lc.enabled,
            },
        )

    # config에 더 이상 없는 LLM은 soft-disable (하드 삭제 금지).
    stale = Llm.filter(enabled=True)
    if config_names:
        stale = stale.exclude(name__in=list(config_names))
    disabled = await stale.update(enabled=False)
    if disabled:
        logger.info("Soft-disabled %d LLM(s) no longer present in config", disabled)

    logger.info("Synced %d LLM(s) from config to DB", len(config_names))
