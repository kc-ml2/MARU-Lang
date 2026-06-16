"""Unified configuration manager - single YAML file."""
import os
import re
import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from maru_lang.configs.models import MaruConfig

logger = logging.getLogger(__name__)

_config: Optional[MaruConfig] = None


def _substitute_env_vars(data: Any) -> Any:
    """Recursively substitute ${ENV:VAR} and ${ENV:VAR:default} in data."""
    if isinstance(data, dict):
        return {k: _substitute_env_vars(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_substitute_env_vars(item) for item in data]
    elif isinstance(data, str):
        pattern = r'\$\{ENV:([A-Z0-9_]+)(?::([^}]*))?\}'

        # Full match → allow type conversion
        full_match = re.fullmatch(pattern, data)
        if full_match:
            var_name = full_match.group(1)
            default = full_match.group(2)
            value = os.getenv(var_name)

            raw = value if value is not None else (default if default is not None else "")

            # Type conversion
            if isinstance(raw, str):
                if raw.lower() in ("true", "false"):
                    return raw.lower() == "true"
                try:
                    return int(raw)
                except ValueError:
                    return raw
            return raw

        # Partial match → string substitution only
        def replacer(match):
            var_name = match.group(1)
            default = match.group(2)
            value = os.getenv(var_name)
            if value is not None:
                return value
            elif default is not None:
                return default
            else:
                logger.warning(f"Environment variable '{var_name}' not found")
                return ""

        return re.sub(pattern, replacer, data)
    return data


def get_config() -> MaruConfig:
    """Return the global MaruConfig (loaded once, cached).

    Looks for maru_app/maru_config.yaml. Returns defaults if not found.
    """
    global _config
    if _config is not None:
        return _config

    config_path = Path.cwd() / "maru_app" / "maru_config.yaml"

    if config_path.exists():
        # Fail closed: if the file exists but we cannot read/parse it, propagate
        # the error instead of silently falling back to insecure defaults.
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        data = _substitute_env_vars(data)
        candidate = MaruConfig.from_dict(data)
        logger.info(f"Loaded config from {config_path}")

        # Security validation — runs BEFORE caching so a failure never leaves
        # an insecure config in `_config` for subsequent callers to pick up.
        if candidate.production:
            _validate_auth_security(candidate)

        _config = candidate
    else:
        # Fail closed in production context: a missing config file must not
        # silently bootstrap an insecure default (production=False) — that
        # would bypass `_validate_auth_security` and run with empty secrets.
        # Opt-in via `MARU_PRODUCTION=1` (set by the deployment/runtime env).
        if os.getenv("MARU_PRODUCTION") == "1":
            raise FileNotFoundError(
                f"MARU_PRODUCTION=1 but maru_config.yaml not found at {config_path}. "
                "Refusing to start with insecure defaults. "
                "Run `maru install` or mount the config before startup."
            )
        logger.info("No maru_config.yaml found, using defaults")
        _config = MaruConfig()

    return _config


_KNOWN_INSECURE_SECRETS = frozenset({
    "",
    "your-secret-key-change-in-production",
    "change-me",
    "secret",
})
_KNOWN_INSECURE_SALTS = frozenset({"", "some-salt", "salt"})
_MIN_SECRET_KEY_LENGTH = 32
_MIN_SALT_LENGTH = 16


def _validate_auth_security(config: MaruConfig) -> None:
    """Hard-fail when production auth credentials are missing, default, or too short."""
    if not config.production:
        return

    secret_key = (config.auth.secret_key or "").strip()
    if secret_key in _KNOWN_INSECURE_SECRETS:
        raise ValueError(
            "SECURITY: production=True but auth.secret_key is empty or a known default. "
            "Set SECRET_KEY env var to a strong random value."
        )
    if len(secret_key) < _MIN_SECRET_KEY_LENGTH:
        raise ValueError(
            f"SECURITY: production=True requires auth.secret_key >= {_MIN_SECRET_KEY_LENGTH} chars (got {len(secret_key)})."
        )

    salt = (config.auth.salt or "").strip()
    if salt in _KNOWN_INSECURE_SALTS:
        raise ValueError(
            "SECURITY: production=True but auth.salt is empty or a known default. "
            "Set SALT env var to a unique random value."
        )
    if len(salt) < _MIN_SALT_LENGTH:
        raise ValueError(
            f"SECURITY: production=True requires auth.salt >= {_MIN_SALT_LENGTH} chars (got {len(salt)})."
        )


def reload_config() -> MaruConfig:
    """Force reload configuration from file."""
    global _config
    _config = None
    return get_config()
