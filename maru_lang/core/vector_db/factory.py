"""
VectorDB 팩토리 - VectorDB 인스턴스 생성
"""
from typing import Optional
from maru_lang.core.vector_db.base import VectorDB
from maru_lang.models.vector_db import (
    BaseVectorDBConfig,
    ChromaDBConfig,
    MilvusConfig,
    LanceDBConfig,
    PineconeConfig,
    get_vector_db_config_from_settings,
)


def get_vector_db(config: Optional[BaseVectorDBConfig] = None) -> VectorDB:
    """
    VectorDB 인스턴스 생성

    Args:
        config: VectorDB 설정 (None이면 system_config.yaml의 vector_db.type에 따라 자동 생성)

    Returns:
        VectorDB: VectorDB 인스턴스

    Raises:
        ValueError: 지원하지 않는 VectorDB 타입인 경우

    Examples:
        # system_config.yaml의 vector_db.type에 따라 자동 생성
        vdb = get_vector_db()  # type이 'chroma'면 ChromaDB, 'milvus'면 Milvus

        # 커스텀 ChromaDB 생성
        config = ChromaDBConfig(
            persist_dir="/path/to/chromadb",
            collection_name="my_collection",
        )
        vdb = get_vector_db(config)
    """
    # config가 없으면 system_config에서 자동으로 적절한 타입 선택
    if config is None:
        config = get_vector_db_config_from_settings()

    # ChromaDB
    if isinstance(config, ChromaDBConfig):
        from maru_lang.core.vector_db.chroma import ChromaVectorDB
        return ChromaVectorDB(
            persist_dir=config.persist_dir,
            collection_name=config.collection_name,
        )

    # Milvus
    elif isinstance(config, MilvusConfig):
        from maru_lang.core.vector_db.milvus import MilvusVectorDB
        return MilvusVectorDB(
            host=config.host,
            port=config.port,
            user=config.user,
            password=config.password,
            collection_name=config.collection_name,
        )

    # LanceDB
    elif isinstance(config, LanceDBConfig):
        from maru_lang.core.vector_db.lancedb import LanceVectorDB
        return LanceVectorDB(
            persist_dir=config.persist_dir,
            table_name=config.table_name,
        )

    # Pinecone (향후 확장)
    elif isinstance(config, PineconeConfig):
        # from maru_lang.core.vector_db.pinecone import PineconeVectorDB
        # return PineconeVectorDB(...)
        raise NotImplementedError("Pinecone support is not yet implemented")

    else:
        raise ValueError(f"Unsupported VectorDB config type: {type(config)}")
