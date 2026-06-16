"""LLM 배정/동기화 서비스.

config(`maru_config.yaml`의 `llms:`)를 진실 원천으로, DB `Llm` 테이블을 미러로
유지하고(`sync_llms_from_config`), 가입 사용자에게 비율 기반으로 LLM을 배정하며
(`assign_balanced_llm`), 메시지 처리 시 사용자에게 실제 적용할 LLM을 해석한다
(`resolve_user_llm_name`).
"""
import logging
from typing import Optional

from maru_lang.configs import get_config
from maru_lang.core.relation_db.models.llm import Llm
from maru_lang.core.relation_db.models.auth import User

logger = logging.getLogger(__name__)


async def sync_llms_from_config() -> None:
    """config의 LLM 목록을 DB `Llm` 테이블에 미러링한다.

    - config에 있는 LLM은 `name` 기준 upsert (provider/model_name/enabled/weight 갱신).
    - config에서 사라진 LLM은 **삭제하지 않고** `enabled=False`로만 둔다 → 과거
      `Conversation.llm_used` / `User.assigned_llm` FK가 깨지지 않게 한다.
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
                "weight": lc.weight,
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


async def pick_balanced_llm() -> Optional[Llm]:
    """가입 배정용 LLM을 결정적으로 고른다 (least-filled by weight).

    enabled=True & weight>0 인 LLM 중, 현재 배정된 사용자 수를 weight로 나눈 값이
    가장 작은 것을 선택한다. 동률은 `id` 오름차순으로 tie-break (random 미사용).
    """
    candidates = await Llm.filter(enabled=True, weight__gt=0).order_by("id")
    if not candidates:
        return None

    best: Optional[Llm] = None
    best_ratio: Optional[float] = None
    for llm in candidates:
        count = await User.filter(assigned_llm_id=llm.id).count()
        ratio = count / llm.weight
        if best_ratio is None or ratio < best_ratio:
            best_ratio = ratio
            best = llm
    return best


async def assign_balanced_llm(user: User) -> Optional[Llm]:
    """신규 사용자에게 비율 기반으로 LLM을 배정하고 저장한다.

    배정 가능한 LLM이 없으면(미설정 등) 아무것도 하지 않고 None을 반환한다 →
    `assigned_llm`은 null로 남고 런타임에 기본 fallback이 적용된다.
    """
    llm = await pick_balanced_llm()
    if llm is not None:
        user.assigned_llm = llm
        await user.save(update_fields=["assigned_llm_id"])
    return llm


async def list_selectable_llms() -> list[Llm]:
    """사용자가 선택할 수 있는(enabled) LLM 목록을 반환한다 (id 오름차순)."""
    return await Llm.filter(enabled=True).order_by("id")


async def set_user_llm(user: User, llm_id: int) -> Llm:
    """사용자가 자기 LLM을 변경한다. enabled LLM만 선택 가능.

    변경은 다음 메시지부터 적용된다(메시지 처리 시 `resolve_user_llm_name`이
    `assigned_llm`을 다시 읽고, 모든 enabled LLM의 그래프는 startup에 미리
    컴파일돼 있으므로 재기동 불필요).

    Raises:
        ValueError: 해당 id의 LLM이 없거나 비활성(enabled=False)일 때.
    """
    llm = await Llm.get_or_none(id=llm_id)
    if llm is None or not llm.enabled:
        raise ValueError("선택할 수 없는 LLM입니다 (존재하지 않거나 비활성).")
    user.assigned_llm = llm
    await user.save(update_fields=["assigned_llm_id"])
    return llm


async def resolve_user_llm_name(
    user: User,
    available: set[str],
    default: Optional[str],
) -> Optional[str]:
    """이 사용자에게 실제로 적용할 LLM name을 해석한다.

    배정된 LLM이 현재 사용 가능(startup에 컴파일된 enabled 집합 `available`)하면 그
    name을, 아니면(미배정/비활성/삭제) `default`를 반환한다. 반환값은 그래프 선택과
    `Conversation.llm_used` 기록에 함께 쓰이는 **실제 사용** LLM이다.
    """
    name: Optional[str] = None
    if getattr(user, "assigned_llm_id", None) is not None:
        llm = await Llm.get_or_none(id=user.assigned_llm_id)
        if llm is not None:
            name = llm.name

    if name and name in available:
        return name
    return default
