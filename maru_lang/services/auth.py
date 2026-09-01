import hmac
import secrets
from datetime import datetime, timedelta, timezone
from maru_lang.settings import Settings
from maru_lang.utils.security import TokenCodec
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from maru_lang.core.relation_db.models.auth import (
    User,
    UserToken,
    RefreshToken,
    EmailVerificationCode,
)


async def create_or_get_user(email: str) -> tuple[User, bool]:
    user = await User.get_or_none(email=email)
    if user is not None:
        return user, False

    try:
        user = await User.create(
            email=email,
            name=email.split("@", 1)[0],
        )
        return user, True
    except IntegrityError:
        # Concurrent successful verifications for the same address converge on
        # the unique User row instead of surfacing a signup race.
        return await User.get(email=email), False


async def update_user_name(user: User, name: str) -> User:
    """사용자가 본인의 전역 표시명(닉네임)을 변경한다. 본인만 호출 (엔드포인트에서 get_user).

    Raises:
        ValueError: 이름이 비어있을 때.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("이름은 비어 있을 수 없습니다")
    user.name = name
    await user.save(update_fields=["name"])
    return user


async def generate_email_verification_code(email: str) -> EmailVerificationCode:
    code = f"{secrets.randbelow(1_000_000):06d}"

    await EmailVerificationCode.filter(email=email).delete()
    return await EmailVerificationCode.create(email=email, code=code)


async def verify_email_code(email: str, code: str, limit: int = 5) -> bool:
    record = await EmailVerificationCode.get_or_none(email=email)
    if not record or not hmac.compare_digest(record.code, code):
        return False
    expiration_time = record.created_at + timedelta(minutes=limit)
    if expiration_time <= datetime.now(timezone.utc):
        await record.delete()
        return False
    # A conditional delete makes the code single-use even when two verification
    # requests race after reading the same valid row.
    return await EmailVerificationCode.filter(id=record.id).delete() == 1


async def generate_token(
    user_id: int,
    device_id: str,
    *,
    config: Settings,
    tokens: TokenCodec,
) -> tuple[str, str]:

    token_payload = {
        "sub": str(user_id),
    }

    access_token, _ = tokens.create(
        token_payload,
        # Default is one hour
        timedelta(minutes=config.access_token_expire_minutes)
    )
    refresh_token, expires_at = tokens.create(
        token_payload,
        timedelta(minutes=config.refresh_token_expire_minutes))

    await UserToken.filter(user_id=user_id, device_id=device_id).delete()
    await RefreshToken.filter(user_id=user_id, device_id=device_id).delete()

    access_token_expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=config.access_token_expire_minutes)

    await UserToken.create(
        user_id=user_id,
        device_id=device_id,
        token_hash=tokens.hash(access_token),
        expires_at=access_token_expires_at
    )

    # Persist the refresh token
    await RefreshToken.create(
        user_id=user_id,
        device_id=device_id,
        token_hash=tokens.hash(refresh_token),
        expires_at=expires_at
    )

    return access_token, refresh_token


async def _refresh_token_flow_locked(
    refresh_token: str,
    device_id: str,
    *,
    config: Settings,
    tokens: TokenCodec,
) -> tuple[str, str] | None:
    """
    Refresh token을 사용하여 새로운 access token과 refresh token을 발급합니다.
    Rotation 패턴을 적용하여 이전 refresh token은 폐기됩니다.
    """
    payload = tokens.decode(refresh_token)
    if not payload:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    now = datetime.now(timezone.utc)
    refresh_token_hash = tokens.hash(refresh_token)

    # 활성 상태인 refresh token 조회
    active_tokens = await RefreshToken.filter(
        user_id=user_id,
        device_id=device_id,
        revoked_at__isnull=True,
        rotated_at__isnull=True
    ).select_for_update().all()

    # 중복 토큰이 있으면 모두 폐기하고 실패 반환 (비정상 상태)
    if len(active_tokens) > 1:
        await RefreshToken.filter(
            user_id=user_id,
            device_id=device_id,
            revoked_at__isnull=True
        ).update(revoked_at=now)
        return None

    db_refresh = active_tokens[0] if active_tokens else None

    if not db_refresh or db_refresh.token_hash != refresh_token_hash:
        return None

    if db_refresh.expires_at < now:
        return None

    # 새로운 access token 생성
    access_token, _ = tokens.create(
        payload,
        timedelta(minutes=config.access_token_expire_minutes)
    )

    # 새로운 refresh token 생성
    new_refresh_token, new_refresh_expires_at = tokens.create(
        payload,
        timedelta(minutes=config.refresh_token_expire_minutes)
    )

    # 기존 access token 폐기
    await UserToken.filter(
        user_id=user_id,
        device_id=device_id,
        revoked_at__isnull=True
    ).update(revoked_at=now)

    access_token_expires_at = now + timedelta(
        minutes=config.access_token_expire_minutes)

    # 새로운 access token 저장
    await UserToken.create(
        user_id=user_id,
        device_id=device_id,
        token_hash=tokens.hash(access_token),
        expires_at=access_token_expires_at
    )

    # 새로운 refresh token 저장
    new_refresh = await RefreshToken.create(
        user_id=user_id,
        device_id=device_id,
        token_hash=tokens.hash(new_refresh_token),
        expires_at=new_refresh_expires_at
    )

    # 이전 refresh token rotation 처리
    db_refresh.rotated_at = now
    db_refresh.replaced_by = new_refresh
    await db_refresh.save()

    return access_token, new_refresh_token


async def refresh_token_flow(
    refresh_token: str,
    device_id: str,
    *,
    config: Settings,
    tokens: TokenCodec,
) -> tuple[str, str] | None:
    """Atomically rotate one device's refresh token."""
    async with in_transaction():
        return await _refresh_token_flow_locked(
            refresh_token,
            device_id,
            config=config,
            tokens=tokens,
        )


async def revoke_token(user_id: int, device_id: str) -> None:
    """특정 device의 토큰을 폐기 (삭제 대신 revoked_at 설정)"""
    now = datetime.now(timezone.utc)

    await UserToken.filter(
        user_id=user_id,
        device_id=device_id,
        revoked_at__isnull=True
    ).update(revoked_at=now)

    await RefreshToken.filter(
        user_id=user_id,
        device_id=device_id,
        revoked_at__isnull=True
    ).update(revoked_at=now)


async def is_token_valid(
    token: str,
    token_model: type[UserToken] | type[RefreshToken],
    *,
    tokens: TokenCodec,
) -> bool:
    """토큰이 유효한지 확인 (만료, 폐기 여부 체크)"""
    now = datetime.now(timezone.utc)
    token_hashed = tokens.hash(token)

    db_token = await token_model.get_or_none(token_hash=token_hashed)

    if not db_token:
        return False

    if db_token.revoked_at is not None:
        return False

    if db_token.expires_at < now:
        return False

    return True
