import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from jose import jwt
from maru_lang.configs.system_config import get_system_config

config = get_system_config()


def hash_token(token: str) -> str:
    """토큰을 HMAC-SHA256으로 해싱하여 반환"""
    return hmac.new(
        config.auth.salt.encode(),
        token.encode(),
        hashlib.sha256
    ).hexdigest()


def create_jwt_token(
    data: dict,
    expires_delta: timedelta
) -> tuple[str, datetime]:
    """Create a JWT access token and return it with its expiry."""
    expires_at = datetime.now(timezone.utc) + expires_delta
    to_encode = data.copy()
    to_encode.update({
        "exp": expires_at,
        "jti": str(uuid.uuid4()),  # 고유 토큰 ID
    })
    encoded_jwt = jwt.encode(
        to_encode,
        config.auth.secret_key,
        algorithm=config.auth.algorithm)
    return encoded_jwt, expires_at


def decode_token(token: str) -> dict | None:
    """Decode a JWT token and return its payload."""
    try:
        payload = jwt.decode(
            token,
            config.auth.secret_key,
            algorithms=[config.auth.algorithm])
        return payload
    except Exception as e:
        return None
