"""Validated YAML settings with environment overrides."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class Settings:
    """Process configuration loaded once at the application boundary."""

    database_url: str
    secret_key: str
    filesystem_root: Path
    public_url: str = "http://localhost:8000"
    download_url_expire_seconds: int = 300
    search_backend: Literal["auto", "python", "ripgrep"] = "auto"
    ripgrep_path: str | None = None
    allowed_domains: tuple[str, ...] = ()
    delete_files_on_team_delete: bool = False
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    email_template_dir: Path | None = None

    @classmethod
    def from_env(cls, config_path: str | Path | None = None) -> "Settings":
        from maru_lang.config_file import load_config

        values = load_config(config_path or os.getenv("MARU_CONFIG"))
        values.update(os.environ)

        def _required(name):
            value = values.get(name, "").strip()
            if not value:
                raise RuntimeError(f"Required configuration {name} is not set")
            return value

        def _integer(name, default, *, minimum=1):
            try:
                value = int(values.get(name, default))
            except (ValueError, TypeError) as exc:
                raise RuntimeError(f"{name} must be an integer") from exc
            if value < minimum:
                raise RuntimeError(f"{name} must be at least {minimum}")
            return value

        def _boolean(name, default=False):
            raw = values.get(name)
            if raw is None:
                return default
            if raw.lower() in {"1", "true", "yes", "on"}:
                return True
            if raw.lower() in {"0", "false", "no", "off"}:
                return False
            raise RuntimeError(f"{name} must be a boolean")

        database_url = _required("MARU_DATABASE_URL")
        parsed = urlparse(database_url)
        if parsed.scheme not in {"postgres", "postgresql", "asyncpg"}:
            raise RuntimeError("MARU_DATABASE_URL must be a PostgreSQL URL")

        secret_key = _required("MARU_SECRET_KEY")
        if len(secret_key) < 32:
            raise RuntimeError("MARU_SECRET_KEY must contain at least 32 characters")

        root = Path(_required("MARU_FILESYSTEM_ROOT")).expanduser()
        if not root.is_absolute():
            raise RuntimeError("MARU_FILESYSTEM_ROOT must be an absolute path")

        allowed_domains = tuple(
            domain.strip().lower()
            for domain in values.get("MARU_ALLOWED_DOMAINS", "").split(",")
            if domain.strip()
        )
        template_dir = values.get("MARU_EMAIL_TEMPLATE_DIR", "").strip()
        public_url = values.get("MARU_PUBLIC_URL", "http://localhost:8000").rstrip("/")
        public_url_parts = urlparse(public_url)
        if public_url_parts.scheme not in {"http", "https"} or not public_url_parts.netloc:
            raise RuntimeError("MARU_PUBLIC_URL must be an absolute HTTP(S) URL")
        search_backend = values.get("MARU_SEARCH_BACKEND", "auto").strip().lower()
        if search_backend not in {"auto", "python", "ripgrep"}:
            raise RuntimeError(
                "MARU_SEARCH_BACKEND must be auto, python, or ripgrep"
            )

        return cls(
            database_url=database_url,
            secret_key=secret_key,
            filesystem_root=root,
            public_url=public_url,
            download_url_expire_seconds=_integer(
                "MARU_DOWNLOAD_URL_EXPIRE_SECONDS", 300
            ),
            search_backend=search_backend,  # type: ignore[arg-type]
            ripgrep_path=values.get("MARU_RIPGREP_PATH") or None,
            allowed_domains=allowed_domains,
            delete_files_on_team_delete=_boolean(
                "MARU_DELETE_FILES_ON_TEAM_DELETE"
            ),
            smtp_host=values.get("MARU_SMTP_HOST") or None,
            smtp_port=_integer("MARU_SMTP_PORT", 587),
            smtp_username=values.get("MARU_SMTP_USERNAME") or None,
            smtp_password=values.get("MARU_SMTP_PASSWORD") or None,
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
