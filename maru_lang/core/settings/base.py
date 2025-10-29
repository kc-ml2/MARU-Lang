"""
Base application settings
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseAppSettings(BaseSettings):
    """Base application configuration"""

    # Server
    HOST: str = "127.0.0.1"
    PROT: int = 8000
    RELOAD: bool = False
    LOG_LEVEL: str = "info"

    # Environment
    PRODUCTION: bool = False

    model_config = SettingsConfigDict(env_file=".env")
