"""
Unified settings module

All settings are organized by category and combined into a single Settings class.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from .base import BaseAppSettings
from .database import DatabaseSettings
from .auth import AuthSettings
from .email import EmailSettings
from .vector_db import VectorDBSettings
from .external import ExternalSettings


class Settings(
    BaseAppSettings,
    DatabaseSettings,
    AuthSettings,
    EmailSettings,
    VectorDBSettings,
    ExternalSettings,
):
    """
    Unified settings class combining all category-specific settings

    Categories:
    - BaseAppSettings: Server and app configuration
    - DatabaseSettings: RDB configuration
    - AuthSettings: Authentication and security
    - EmailSettings: Email service configuration
    - VectorDBSettings: Vector database configuration
    - ExternalSettings: External services (Langfuse, Slack, etc.)
    """
    model_config = SettingsConfigDict(env_file=".env")


# Global settings instance
settings = Settings()


# Tortoise ORM configuration for Aerich
TORTOISE_ORM = {
    "connections": {"default": settings.DATABASE_URL},
    "apps": {
        "models": {
            "models": ["maru_lang.models", "aerich.models"],
            "default_connection": "default",
        },
    },
    "use_tz": True,
}


__all__ = [
    "Settings",
    "settings",
    "TORTOISE_ORM",
    "BaseAppSettings",
    "DatabaseSettings",
    "AuthSettings",
    "EmailSettings",
    "VectorDBSettings",
    "ExternalSettings",
]
