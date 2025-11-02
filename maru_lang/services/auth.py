from datetime import datetime, timedelta, timezone
import random
import asyncio
from urllib.parse import parse_qs
from maru_lang.configs.system_config import get_system_config
from maru_lang.enums.auth import UserRoleCode

config = get_system_config()
from maru_lang.dependencies.email import EmailService
from maru_lang.utils.security import (
    aes256_decrypt,
    create_jwt_token,
    decode_token,
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
    # Always convert to lowercase
    name = name.lower()
    # 1. Check whether a user group with the same name already exists
    user_group, _ = await UserGroup.get_or_create(name=name)


    return user_group


async def create_or_get_user(
    email: str,
    role: str = UserRoleCode.EDITOR.value,
) -> User:
    role_object, _ = await UserRole.get_or_create(name=role)
    existing_user = await User.get_or_none(email=email)
    # Already registered user
    if existing_user:
        return existing_user

    # 3. Create the user
    new_user = await User.create(
        email=email,
        name=None,  # Defaults to None when not provided
        role=role_object
    )
    try:
        # 4. Optionally create and link a user group based on the email domain
        if config.auth.auto_create_group_by_domain:
            domain = email.split('@')[1].split('.')[0] if '@' in email else 'default'
            group = await create_or_get_user_group(name=domain)
            await UserGroupMembership.create(user=new_user, group=group)

        # 5. Ensure the user is added to the "public" group
        public_group = await create_or_get_user_group(name="public")
        await UserGroupMembership.create(user=new_user, group=public_group)
    except Exception as e:
        print(f"Error creating or getting user group: {e}")
        raise e
    return new_user


async def generate_OTP(email: str, email_service: EmailService | None = None) -> OTP:
    
    if not email_service:
        code = config.auth.default_validation_code
    else:
        code = str(random.randint(100000, 999999))  # Generate a 6-digit code
    
    await OTP.filter(email=email).delete()  # Remove previous codes
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
        timedelta(minutes=config.auth.access_token_expire_minutes)  # Default is one hour
    )
    refresh_token, expires_at = create_jwt_token(
        token_payload,
        timedelta(minutes=config.auth.refresh_token_expire_minutes))

    await UserToken.filter(user_id=user_id, device_id=device_id).delete()
    await RefreshToken.filter(user_id=user_id, device_id=device_id).delete()
    await UserToken.create(
        user_id=user_id,
        device_id=device_id,
        jwt_token=access_token
    )

    # Persist the refresh token
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

    # Compare with the refresh token stored in the database
    # Fetch the most recent one
    if device_id:
        db_refresh = await RefreshToken.filter(
            user_id=user_id,
            device_id=device_id
        ).order_by("-created_at").first()
    else:
        # If device_id is missing, fallback to the latest refresh token for the user (covers SSE without headers)
        db_refresh = await RefreshToken.filter(
            user_id=user_id
        ).order_by("-created_at").first()
    if not db_refresh or db_refresh.refresh_token != refresh_token:
        return None

    if db_refresh.expires_at < datetime.now(timezone.utc):
        return None

    access_token, _ = create_jwt_token(
        payload,
        timedelta(minutes=config.auth.access_token_expire_minutes)  # Default is one hour
    )

    await UserToken.filter(user_id=user_id, device_id=device_id).delete()
    await UserToken.create(
        user_id=user_id,
        device_id=device_id,
        jwt_token=access_token
    )

    # Update the existing refresh-token expiration without rotating the token itself
    db_refresh.expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=config.auth.refresh_token_expire_minutes)
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
