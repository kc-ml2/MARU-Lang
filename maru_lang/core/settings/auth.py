"""
Authentication and security settings
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    """Authentication and security configuration"""

    # Security
    SECRET_KEY: str = "your-secret"  # 기본값 설정해도 됨 (dev 용)
    SALT: str = "some-salt"
    ALGORITHM: str = "HS256"

    # Token expiration
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 30  # 30일

    # Validation
    DEFAULT_VALIDATION_CODE: str = "456123"

    # Auto group creation
    AUTO_CREATE_GROUP_BY_DOMAIN: bool = True

    model_config = SettingsConfigDict(env_file=".env")
