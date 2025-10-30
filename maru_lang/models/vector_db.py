"""
VectorDB 설정 모델
"""
from dataclasses import dataclass, field
from typing import Optional, Union


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
        from maru_lang.configs.system_config import get_system_config
        config = get_system_config()
        return cls(
            persist_dir=config.vector_db.chroma.get_persist_dir_absolute(),
            collection_name=config.vector_db.default_collection_name,
        )


@dataclass
class MilvusConfig(BaseVectorDBConfig):
    """Milvus 전용 설정"""
    host: str = field(default="localhost")
    port: int = field(default=19530)
    user: str = field(default="root")
    password: str = field(default="Milvus")
    collection_name: str = field(default="")
    db_type: str = field(default="milvus", init=False)

    @classmethod
    def from_settings(cls) -> "MilvusConfig":
        """Settings로부터 기본 Milvus 설정 생성"""
        from maru_lang.configs.system_config import get_system_config
        config = get_system_config()
        return cls(
            host=config.vector_db.milvus.host,
            port=config.vector_db.milvus.port,
            user=config.vector_db.milvus.user,
            password=config.vector_db.milvus.password,
            collection_name=config.vector_db.default_collection_name,
        )


@dataclass
class PineconeConfig(BaseVectorDBConfig):
    """Pinecone 전용 설정 (향후 확장)"""
    api_key: str = field(default="")
    environment: str = field(default="")
    index_name: str = field(default="")
    db_type: str = field(default="pinecone", init=False)


def get_vector_db_config_from_settings() -> Union[ChromaDBConfig, MilvusConfig]:
    """
    system_config.yaml의 vector_db.type에 따라 적절한 VectorDB 설정 반환

    Returns:
        ChromaDBConfig or MilvusConfig: 설정된 VectorDB 타입에 맞는 설정 객체

    Raises:
        ValueError: 지원하지 않는 VectorDB 타입인 경우
    """
    from maru_lang.configs.system_config import get_system_config
    config = get_system_config()

    db_type = config.vector_db.type.lower()

    if db_type == "chroma":
        return ChromaDBConfig.from_settings()
    elif db_type == "milvus":
        return MilvusConfig.from_settings()
    else:
        raise ValueError(
            f"Unsupported vector_db.type: {db_type}. "
            f"Supported types: 'chroma', 'milvus'"
        )