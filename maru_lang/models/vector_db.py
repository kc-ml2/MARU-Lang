"""
VectorDB 설정 모델
"""
from dataclasses import dataclass, field
from typing import Optional


# ========== VectorDB Config (상속 기반) ==========

@dataclass
class BaseVectorDBConfig:
    """VectorDB 기본 설정 (모든 VectorDB 공통)"""
    db_type: str


@dataclass
class ChromaDBConfig(BaseVectorDBConfig):
    """ChromaDB 전용 설정"""
    persist_dir: str = field(default="")
    collection_name: str = field(default="")
    db_type: str = field(default="chromadb", init=False)

    @classmethod
    def from_settings(cls) -> "ChromaDBConfig":
        """Settings로부터 기본 ChromaDB 설정 생성"""
        from maru_lang.core.settings import settings
        return cls(
            persist_dir=settings.CHROMA_PERSIST_DIR_ABSOLUTE,
            collection_name=settings.DEFAULT_DB_COLLECTION_NAME,
        )


@dataclass
class PineconeConfig(BaseVectorDBConfig):
    """Pinecone 전용 설정 (향후 확장)"""
    api_key: str = field(default="")
    environment: str = field(default="")
    index_name: str = field(default="")
    db_type: str = field(default="pinecone", init=False)


# Backward compatibility - 기존 코드 호환용
VectorDBConfig = ChromaDBConfig
