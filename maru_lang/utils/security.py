"""JWT and token hashing primitives with explicit configuration."""
from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from jose import jwt


@dataclass(frozen=True, slots=True)
class TokenCodec:
    secret_key: str
    salt: str
    algorithm: str = "HS256"

    def hash(self, token: str) -> str:
        return hmac.new(
            self.salt.encode(), token.encode(), hashlib.sha256
        ).hexdigest()

    def create(
        self, data: dict, expires_delta: timedelta
    ) -> tuple[str, datetime]:
        expires_at = datetime.now(timezone.utc) + expires_delta
        payload = {**data, "exp": expires_at, "jti": str(uuid.uuid4())}
        return (
            jwt.encode(payload, self.secret_key, algorithm=self.algorithm),
            expires_at,
        )

    def decode(self, token: str) -> dict | None:
        try:
            return jwt.decode(
                token, self.secret_key, algorithms=[self.algorithm]
            )
        except Exception:
            return None
