"""Validated, environment-only application settings."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value


def _integer(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name)
    try:
        value = default if raw is None else int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}")
    return value


def _boolean(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean")


@dataclass(frozen=True, slots=True)
class Settings:
    """Process configuration loaded once at the application boundary."""

    database_url: str
    secret_key: str
    salt: str
    filesystem_root: Path
    access_token_expire_minutes: int = 120
    refresh_token_expire_minutes: int = 43_200
    allowed_domains: tuple[str, ...] = ()
    delete_files_on_team_delete: bool = False
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    email_template_dir: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        database_url = _required("MARU_DATABASE_URL")
        parsed = urlparse(database_url)
        if parsed.scheme not in {"postgres", "postgresql", "asyncpg"}:
            raise RuntimeError("MARU_DATABASE_URL must be a PostgreSQL URL")

        secret_key = _required("MARU_SECRET_KEY")
        if len(secret_key) < 32:
            raise RuntimeError("MARU_SECRET_KEY must contain at least 32 characters")
        salt = _required("MARU_SALT")
        if len(salt) < 16:
            raise RuntimeError("MARU_SALT must contain at least 16 characters")

        root = Path(_required("MARU_FILESYSTEM_ROOT")).expanduser()
        if not root.is_absolute():
            raise RuntimeError("MARU_FILESYSTEM_ROOT must be an absolute path")

        allowed_domains = tuple(
            domain.strip().lower()
            for domain in os.getenv("MARU_ALLOWED_DOMAINS", "").split(",")
            if domain.strip()
        )
        template_dir = os.getenv("MARU_EMAIL_TEMPLATE_DIR", "").strip()

        return cls(
            database_url=database_url,
            secret_key=secret_key,
            salt=salt,
            filesystem_root=root,
            access_token_expire_minutes=_integer(
                "MARU_ACCESS_TOKEN_EXPIRE_MINUTES", 120
            ),
            refresh_token_expire_minutes=_integer(
                "MARU_REFRESH_TOKEN_EXPIRE_MINUTES", 43_200
            ),
            allowed_domains=allowed_domains,
            delete_files_on_team_delete=_boolean(
                "MARU_DELETE_FILES_ON_TEAM_DELETE"
            ),
            smtp_host=os.getenv("MARU_SMTP_HOST") or None,
            smtp_port=_integer("MARU_SMTP_PORT", 587),
            smtp_username=os.getenv("MARU_SMTP_USERNAME") or None,
            smtp_password=os.getenv("MARU_SMTP_PASSWORD") or None,
            email_template_dir=(
                Path(template_dir).expanduser() if template_dir else None
            ),
        )

    def is_domain_allowed(self, email: str) -> bool:
        if not self.allowed_domains:
            return True
        parts = (email or "").strip().split("@")
        return (
            len(parts) == 2
            and bool(parts[0])
            and parts[1].lower() in self.allowed_domains
        )
