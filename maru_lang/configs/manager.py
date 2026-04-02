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
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            data = _substitute_env_vars(data)
            _config = MaruConfig.from_dict(data)
            logger.info(f"Loaded config from {config_path}")
        except Exception as e:
            logger.error(f"Failed to load config: {e}, using defaults")
            _config = MaruConfig()
    else:
        logger.info("No maru_config.yaml found, using defaults")
        _config = MaruConfig()

    return _config


def reload_config() -> MaruConfig:
    """Force reload configuration from file."""
    global _config
    _config = None
    return get_config()
