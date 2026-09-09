"""Shared API-token authentication for HTTP management routes."""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from maru_lang.core.relation_db.models.auth import User
from maru_lang.services.api_tokens import authenticate_token

bearer_scheme = HTTPBearer(auto_error=False)


async def get_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    record = await authenticate_token(credentials.credentials) if credentials else None
    user = await User.get_or_none(id=record.user_id) if record else None
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Missing, invalid, expired or revoked API token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
