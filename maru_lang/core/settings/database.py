"""
Database settings
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal
from pathlib import Path


class DatabaseSettings(BaseSettings):
    """Database configuration"""

    # DB Type
    DB_TYPE: Literal["postgres", "sqlite"] = "sqlite"

    # Common DB settings
    DB_USERNAME: str | None = None
    DB_PASSWORD: str | None = None
    DB_HOST: str | None = None
    DB_PORT: str | None = None
    DB_NAME: str = "chatbot"  # sqlite 파일 이름 기본값

    model_config = SettingsConfigDict(env_file=".env")

    @property
    def DATABASE_URL(self) -> str:
        """Generate database URL based on DB_TYPE"""
        if self.DB_TYPE == "sqlite":
            # 프로젝트 루트 디렉토리의 절대 경로를 사용
            project_root = Path(__file__).parent.parent.parent.parent
            db_path = project_root / f"{self.DB_NAME}.db"
            return f"sqlite:///{db_path.absolute()}"
        elif self.DB_TYPE == "postgres":
            if not all([self.DB_USERNAME, self.DB_PASSWORD, self.DB_HOST, self.DB_PORT, self.DB_NAME]):
                raise ValueError("PostgreSQL 설정이 불완전합니다.")
            return f"postgres://{self.DB_USERNAME}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        else:
            raise ValueError("지원하지 않는 DB_TYPE 입니다.")
