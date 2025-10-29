"""
External service settings
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExternalSettings(BaseSettings):
    """External service configuration"""

    # Slack
    SLACK_WEBHOOK_URL: str = ""
    SLACK_INFO_CHANNEL: str | None = None
    SLACK_DEBUG_CHANNEL: str | None = None
    SLACK_ERROR_CHANNEL: str | None = None
    SLACK_REPORT_CHANNEL: str | None = None

    model_config = SettingsConfigDict(env_file=".env")
