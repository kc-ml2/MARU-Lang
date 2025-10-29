"""
Email service settings
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class EmailSettings(BaseSettings):
    """Email service configuration"""

    # Email service type
    EMAIL_SERVICE_TYPE: Literal["o365", "smtp"] = "o365"

    # Email addresses
    FEEDBACK_EMAIL: str | None = None
    SENDER_EMAIL: str | None = None

    # Office 365
    O365_CLIENT_ID: str | None = None
    O365_CLIENT_SECRET: str | None = None
    O365_TENANT_ID: str | None = None

    # TODO: SMTP settings can be added here
    # SMTP_HOST: str | None = None
    # SMTP_PORT: int = 587
    # SMTP_USERNAME: str | None = None
    # SMTP_PASSWORD: str | None = None

    model_config = SettingsConfigDict(env_file=".env")
