"""Strict YAML configuration, translated to the existing environment keys."""
from pathlib import Path

import yaml

SECTIONS = {
    "database": {"url": "DATABASE_URL"},
    "auth": {key: key.upper() for key in (
        "secret_key", "allowed_domains",
    )},
    "filesystem": {
        "root": "FILESYSTEM_ROOT", "search_backend": "SEARCH_BACKEND",
        "ripgrep_path": "RIPGREP_PATH",
        "delete_files_on_team_delete": "DELETE_FILES_ON_TEAM_DELETE",
    },
    "server": {
        "public_url": "PUBLIC_URL",
        "download_url_expire_seconds": "DOWNLOAD_URL_EXPIRE_SECONDS",
    },
    "smtp": {"host": "SMTP_HOST", "port": "SMTP_PORT",
             "username": "SMTP_USERNAME", "password": "SMTP_PASSWORD",
             "template_dir": "EMAIL_TEMPLATE_DIR"},
}


def load_config(path: str | Path | None) -> dict[str, str]:
    if path is None:
        return {}
    try:
        data = yaml.safe_load(Path(path).expanduser().read_text())
    except yaml.YAMLError:
        # YAML errors can contain source lines with credentials.
        raise RuntimeError("Invalid YAML configuration") from None
    if not isinstance(data, dict):
        raise RuntimeError("Configuration must be a YAML mapping")
    result = {}
    for section, entries in data.items():
        if section not in SECTIONS or not isinstance(entries, dict):
            raise RuntimeError(f"Unknown or invalid configuration section: {section}")
        for key, value in entries.items():
            if key not in SECTIONS[section]:
                raise RuntimeError(f"Unknown configuration key: {section}.{key}")
            if value is None:
                continue
            if section == "auth" and key == "allowed_domains" and isinstance(value, list):
                if not all(isinstance(item, str) for item in value):
                    raise RuntimeError("auth.allowed_domains must contain strings")
                value = ",".join(value)
            if not isinstance(value, (str, int, bool)):
                raise RuntimeError(f"Invalid configuration value type: {section}.{key}")
            result[f"MARU_{SECTIONS[section][key]}"] = str(value)
    return result
