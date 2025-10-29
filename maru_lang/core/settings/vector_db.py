"""
Vector database settings
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal
from pathlib import Path


class VectorDBSettings(BaseSettings):
    """Vector database configuration"""

    # Vector DB type
    VECTOR_DB_TYPE: Literal["chroma", "milvus"] = "chroma"
    DEFAULT_DB_COLLECTION_NAME: str = "maru"
    EMBEDDING_MODEL: str = "BAAI/bge-m3"

    # Vector DB에 텍스트 저장 여부 (False시 RDB에서만 관리, 저장공간 절약)
    VECTOR_DB_STORE_TEXT: bool = True

    # Chroma settings
    CHROMA_PERSIST_DIR: str = "data/chroma/"

    # Milvus settings
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    MILVUS_USER: str = "root"
    MILVUS_PASSWORD: str = "Milvus"

    model_config = SettingsConfigDict(env_file=".env")

    @property
    def CHROMA_PERSIST_DIR_ABSOLUTE(self) -> str:
        """프로젝트 루트 기준 절대 경로로 Chroma 저장 디렉토리 반환"""
        project_root = Path(__file__).parent.parent.parent.parent
        chroma_path = project_root / self.CHROMA_PERSIST_DIR
        return str(chroma_path.absolute())
