import random
import secrets
from datetime import datetime, timedelta, timezone
from maru_lang.configs import get_config
from maru_lang.dependencies.email import EmailService
from maru_lang.utils.security import (
    create_jwt_token,
    decode_token,
    hash_token,
)

from maru_lang.core.relation_db.models.auth import (
    User,
    UserToken,
    RefreshToken,
    UserRole,
    EmailVerificationCode,
    UserChatToken,
    TeamMember,
)
from maru_lang.enums.auth import UserRoleCode
from maru_lang.services.llm import assign_balanced_llm

config = get_config()


async def create_or_get_user(email: str) -> User:
    if user := await User.get_or_none(email=email):
        await _activate_anonymous_user(user)
        return user
    try:
        name = email.split('@')[0]
    except Exception:
        name = None

    editor_role, _ = await UserRole.get_or_create(
        name=UserRoleCode.EDITOR.value,
        defaults={"description": "일반 사용자"},
    )
    new_user = await User.create(
        email=email,
        name=name,
        role=editor_role,
    )
    await assign_balanced_llm(new_user)
    return new_user


async def _activate_anonymous_user(user: User) -> None:
    """익명 유저가 최초 로그인하면 anonymous → editor 롤 변경 + pending 멤버십을 member로 변경"""
    if not user.role_id:
        # role이 없는 기존 유저에게 editor 롤 부여
        editor_role, _ = await UserRole.get_or_create(
            name=UserRoleCode.EDITOR.value,
            defaults={"description": "일반 사용자"},
        )
        user.role = editor_role
        await user.save()
        return

    role = await UserRole.get_or_none(id=user.role_id)
    if not role or role.name != UserRoleCode.ANONYMOUS.value:
        return

    # anonymous → editor 롤 변경
    editor_role, _ = await UserRole.get_or_create(
        name=UserRoleCode.EDITOR.value,
        defaults={"description": "일반 사용자"},
    )
    user.role = editor_role
    await user.save()

    # pending 멤버십을 member로 변경
    await TeamMember.filter(user=user, role="pending").update(role="member")


async def set_user_name(user: User, name: str):
    user.name = name
    await user.save()


async def generate_email_verification_code(
    email: str,
    email_service: EmailService | None = None
) -> EmailVerificationCode:
    if not email_service:
        if config.production:
            raise ValueError("Email service is not configured")
        code = config.auth.default_validation_code
    else:
        code = str(random.randint(100000, 999999))

    await EmailVerificationCode.filter(email=email).delete()
    return await EmailVerificationCode.create(email=email, code=code)


async def verify_email_code(email: str, code: str, limit: int = 5) -> bool:
    record = await EmailVerificationCode.get_or_none(email=email)
    if not record or record.code != code:
        return False
    expiration_time = record.created_at + timedelta(minutes=limit)
    return expiration_time > datetime.now(timezone.utc)


async def generate_token(
    user_id: int,
    device_id: str
) -> tuple[str, str]:

    token_payload = {
        "sub": str(user_id),
    }

    access_token, _ = create_jwt_token(
        token_payload,
        # Default is one hour
        timedelta(minutes=config.auth.access_token_expire_minutes)
    )
    refresh_token, expires_at = create_jwt_token(
        token_payload,
        timedelta(minutes=config.auth.refresh_token_expire_minutes))

    await UserToken.filter(user_id=user_id, device_id=device_id).delete()
    await RefreshToken.filter(user_id=user_id, device_id=device_id).delete()

    access_token_expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=config.auth.access_token_expire_minutes)

    await UserToken.create(
        user_id=user_id,
        device_id=device_id,
        token_hash=hash_token(access_token),
        expires_at=access_token_expires_at
    )

    # Persist the refresh token
    await RefreshToken.create(
        user_id=user_id,
        device_id=device_id,
        token_hash=hash_token(refresh_token),
        expires_at=expires_at
    )

    return access_token, refresh_token


async def refresh_token_flow(
    refresh_token: str,
    device_id: str,
) -> tuple[str, str] | None:
    """
    Refresh token을 사용하여 새로운 access token과 refresh token을 발급합니다.
    Rotation 패턴을 적용하여 이전 refresh token은 폐기됩니다.
    """
    payload = decode_token(refresh_token)
    if not payload:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    now = datetime.now(timezone.utc)
    refresh_token_hash = hash_token(refresh_token)

    # 활성 상태인 refresh token 조회
    active_tokens = await RefreshToken.filter(
        user_id=user_id,
        device_id=device_id,
        revoked_at__isnull=True,
        rotated_at__isnull=True
    ).all()

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
    access_token, _ = create_jwt_token(
        payload,
        timedelta(minutes=config.auth.access_token_expire_minutes)
    )

    # 새로운 refresh token 생성
    new_refresh_token, new_refresh_expires_at = create_jwt_token(
        payload,
        timedelta(minutes=config.auth.refresh_token_expire_minutes)
    )

    # 기존 access token 폐기
    await UserToken.filter(
        user_id=user_id,
        device_id=device_id,
        revoked_at__isnull=True
    ).update(revoked_at=now)

    access_token_expires_at = now + timedelta(
        minutes=config.auth.access_token_expire_minutes)

    # 새로운 access token 저장
    await UserToken.create(
        user_id=user_id,
        device_id=device_id,
        token_hash=hash_token(access_token),
        expires_at=access_token_expires_at
    )

    # 새로운 refresh token 저장
    new_refresh = await RefreshToken.create(
        user_id=user_id,
        device_id=device_id,
        token_hash=hash_token(new_refresh_token),
        expires_at=new_refresh_expires_at
    )

    # 이전 refresh token rotation 처리
    db_refresh.rotated_at = now
    db_refresh.replaced_by = new_refresh
    await db_refresh.save()

    return access_token, new_refresh_token


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


async def revoke_all_user_tokens(user_id: int) -> None:
    """사용자의 모든 토큰을 폐기 (보안 이슈 발생 시 사용)"""
    now = datetime.now(timezone.utc)

    await UserToken.filter(
        user_id=user_id,
        revoked_at__isnull=True
    ).update(revoked_at=now)

    await RefreshToken.filter(
        user_id=user_id,
        revoked_at__isnull=True
    ).update(revoked_at=now)

    await UserChatToken.filter(
        user_id=user_id,
        revoked_at__isnull=True
    ).update(revoked_at=now)


async def is_token_valid(
    token: str,
    token_model: type[UserToken] | type[RefreshToken] | type[UserChatToken]
) -> bool:
    """토큰이 유효한지 확인 (만료, 폐기 여부 체크)"""
    now = datetime.now(timezone.utc)
    token_hashed = hash_token(token)

    db_token = await token_model.get_or_none(token_hash=token_hashed)

    if not db_token:
        return False

    if db_token.revoked_at is not None:
        return False

    if db_token.expires_at < now:
        return False

    return True


async def generate_chat_token(
    user_id: int,
    expires_minutes: int = 30
) -> str:
    """일회용 채팅 토큰 생성"""
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)

    await UserChatToken.create(
        user_id=user_id,
        token_hash=hash_token(token),
        expires_at=now + timedelta(minutes=expires_minutes)
    )

    return token


async def verify_chat_token(token: str) -> User | None:
    """
    채팅 토큰 검증 및 사용 처리 (일회용)
    Returns: User if valid, None otherwise
    """
    now = datetime.now(timezone.utc)
    token_hashed = hash_token(token)

    chat_token = await UserChatToken.get_or_none(
        token_hash=token_hashed
    ).prefetch_related('user')

    if not chat_token:
        return None

    if chat_token.revoked_at is not None:
        return None

    if chat_token.expires_at < now:
        return None

    if chat_token.used_at is not None:
        return None

    # 일회용: 사용 처리
    chat_token.used_at = now
    await chat_token.save()

    return chat_token.user


async def revoke_chat_token(token: str) -> bool:
    """채팅 토큰 폐기"""
    now = datetime.now(timezone.utc)
    token_hashed = hash_token(token)

    chat_token = await UserChatToken.get_or_none(token_hash=token_hashed)
    if not chat_token:
        return False

    chat_token.revoked_at = now
    await chat_token.save()
    return True
