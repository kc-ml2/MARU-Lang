"""Short-lived download capability signing; not user authentication."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from jose import jwt


@dataclass(frozen=True, slots=True)
class TokenCodec:
    secret_key: str
    algorithm: str = "HS256"

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
