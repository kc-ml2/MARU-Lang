"""Long-lived, individually revocable API credentials."""
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from maru_lang.core.relation_db.models.auth import ApiToken, User


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def parse_expiry(value: str | None) -> timedelta | None:
    if value is None:
        return None
    match = re.fullmatch(r"([1-9][0-9]*)([dhm])", value)
    if match is None:
        raise ValueError("Expiry must be a positive duration such as 90d, 12h or 30m")
    try:
        return timedelta(seconds=int(match[1]) * {"d": 86400, "h": 3600, "m": 60}[match[2]])
    except OverflowError:
        raise ValueError("Expiry is too large") from None


async def issue_token(user: User, duration: timedelta | None = None):
    expires_at = datetime.now(timezone.utc) + duration if duration else None
    token = "maru_" + secrets.token_urlsafe(32)
    record = await ApiToken.create(
        user=user, token_hash=token_hash(token), expires_at=expires_at
    )
    return record, token


async def authenticate_token(token: str) -> ApiToken | None:
    if not re.fullmatch(r"maru_[A-Za-z0-9_-]{43}", token):
        return None
    record = await ApiToken.get_or_none(token_hash=token_hash(token), revoked_at=None)
    if record is None:
        return None
    if record.expires_at is not None and record.expires_at <= datetime.now(timezone.utc):
        return None
    if not await User.exists(id=record.user_id):
        return None
    return record


async def revoke_token(token_id: int) -> None:
    record = await ApiToken.get_or_none(id=token_id)
    if record is None:
        raise ValueError("API token not found")
    if record.revoked_at is None:
        record.revoked_at = datetime.now(timezone.utc)
        await record.save(update_fields=["revoked_at"])
