from datetime import datetime, timedelta, timezone
import random
import asyncio
from urllib.parse import parse_qs
from maru_lang.core.settings import settings
from maru_lang.enums.auth import UserRoleCode
from maru_lang.dependencies.email import EmailService
from maru_lang.utils.security import (
    aes256_decrypt,
    create_jwt_token,
    decode_token,
)
from maru_lang.core.relation_db.models.documents import (
    DocumentGroup,
    GroupPermission,
    PermissionAction,
)
from maru_lang.core.relation_db.models.auth import (
    User,
    UserGroup,
    UserGroupMembership,
    UserToken,
    RefreshToken,
    UserRole,
    OTP,
)

async def get_user_groups(user: User) -> list[UserGroup]:
    return [
        user_group_membership.group
        for user_group_membership in await UserGroupMembership.filter(user=user).prefetch_related('group').all()
    ]

async def create_or_get_user_group(name: str) -> UserGroup:
    # 무조건 소문자로
    name = name.lower()
    # 1. 먼저 같은 이름의 UserGroup이 이미 있는지 체크
    user_group, _ = await UserGroup.get_or_create(name=name)
    # 2. 같은 이름의 DocumentGroup 존재하면 Permission 연결
    doc_group, _ = await DocumentGroup.get_or_create(name=name)
    await asyncio.gather(
        GroupPermission.get_or_create(
            user_group=user_group,
            document_group=doc_group,
            action=PermissionAction.READ
        ),
        GroupPermission.get_or_create(
            user_group=user_group,
            document_group=doc_group,
            action=PermissionAction.WRITE
        )
    )
    return user_group


async def create_or_get_user(
    email: str,
    role: str = UserRoleCode.EDITOR.value,
) -> User:
    role_object, _ = await UserRole.get_or_create(name=role)
    existing_user = await User.get_or_none(email=email)
    # 이미 등록된 사용자
    if existing_user:
        return existing_user

    # 3. User 생성
    new_user = await User.create(
        email=email,
        name=None,  # 이름은 따로 입력하지 않으면 None
        role=role_object
    )

    # 4. 설정에 따라 이메일 도메인 기반 UserGroup 자동 생성 및 연결
    if settings.AUTO_CREATE_GROUP_BY_DOMAIN:
        domain = email.split('@')[1].split('.')[0] if '@' in email else 'default'
        group = await create_or_get_user_group(name=domain)
        await UserGroupMembership.create(user=new_user, group=group)

    # 5. public 이라는 그룹에 추가
    public_group = await create_or_get_user_group(name="public")
    await UserGroupMembership.create(user=new_user, group=public_group)

    return new_user


async def generate_OTP(email: str, email_service: EmailService | None = None) -> OTP:
    
    if not email_service:
        code = settings.DEFAULT_VALIDATION_CODE
    else:
        code = str(random.randint(100000, 999999))  # 6자리 인증코드 생성
    
    await OTP.filter(email=email).delete()  # 기존 코드 삭제
    otp = await OTP.create(email=email, code=code)
    return otp


async def verify_OTP(email: str, code: str) -> bool:
    otp = await OTP.get(email=email)
    return otp.code == code and await otp.is_valid()


async def generate_token(
    user_id: int,
    role_id: int,
    device_id: str
) -> tuple[str, str]:
    user_role = await UserRole.get(id=role_id)

    token_payload = {
        "sub": str(user_id),
        "user_role": user_role.name,
    }

    access_token, _ = create_jwt_token(
        token_payload,
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)  # 1시간
    )
    refresh_token, expires_at = create_jwt_token(
        token_payload,
        timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES))

    await UserToken.filter(user_id=user_id, device_id=device_id).delete()
    await RefreshToken.filter(user_id=user_id, device_id=device_id).delete()
    await UserToken.create(
        user_id=user_id,
        device_id=device_id,
        jwt_token=access_token
    )

    # Refresh Token 저장
    await RefreshToken.create(
        user_id=user_id,
        device_id=device_id,
        refresh_token=refresh_token,
        expires_at=expires_at
    )

    return access_token, refresh_token


async def refresh_token_flow(
    refresh_token: str,
    device_id: str | None,
) -> str | None:
    payload = decode_token(refresh_token)
    if not payload:
        return None
    
    user_id = payload.get("sub")
    if not user_id:
        return None

    # DB에 저장된 refresh_token과 비교
    # 가장 최신으로 가져온다.
    if device_id:
        db_refresh = await RefreshToken.filter(
            user_id=user_id,
            device_id=device_id
        ).order_by("-created_at").first()
    else:
        # device_id가 없으면 해당 사용자에 대한 최신 refresh를 사용 (SSE 등 헤더를 못 붙이는 경우 지원)
        db_refresh = await RefreshToken.filter(
            user_id=user_id
        ).order_by("-created_at").first()
    if not db_refresh or db_refresh.refresh_token != refresh_token:
        return None

    if db_refresh.expires_at < datetime.now(timezone.utc):
        return None

    access_token, _ = create_jwt_token(
        payload,
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)  # 1시간
    )

    await UserToken.filter(user_id=user_id, device_id=device_id).delete()
    await UserToken.create(
        user_id=user_id,
        device_id=device_id,
        jwt_token=access_token
    )

    # refresh_token은 변경하지 않고 갱신만 해준다.
    db_refresh.expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)
    await db_refresh.save()

    return access_token


async def delete_token(user_id: int, device_id: str):
    await UserToken.filter(user_id=user_id, device_id=device_id).delete()
    await RefreshToken.filter(user_id=user_id, device_id=device_id).delete()


# Deprecated: Use EmailService instead
def send_otp_to_email(receiver_email: str, verification_code: str):
    from maru_lang.dependencies.email import get_email_manager

    email_service = get_email_manager()
    if email_service:
        return email_service.send_otp(receiver_email, verification_code)
    return False
