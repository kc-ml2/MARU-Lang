"""
VectorDB 팩토리 - VectorDB 인스턴스 생성
"""
from typing import Optional
from maru_lang.core.vector_db.base import VectorDB
from maru_lang.models.vector_db import BaseVectorDBConfig, ChromaDBConfig, PineconeConfig


def get_vector_db(config: Optional[BaseVectorDBConfig] = None) -> VectorDB:
    """
    VectorDB 인스턴스 생성

    Args:
        config: VectorDB 설정 (None이면 settings에서 기본 ChromaDB 생성)

    Returns:
        BaseVectorDB: VectorDB 인스턴스

    Raises:
        ValueError: 지원하지 않는 VectorDB 타입인 경우

    Examples:
        # Settings에서 기본 ChromaDB 생성
        vdb = get_vector_db()

        # 커스텀 ChromaDB 생성
        config = ChromaDBConfig(
            db_type="chromadb",
            persist_dir="/path/to/chromadb",
            collection_name="my_collection",
        )
        vdb = get_vector_db(config)
    """
    # config가 없으면 settings에서 기본 ChromaDB 생성
    if config is None:
        config = ChromaDBConfig.from_settings()

    # ChromaDB
    if isinstance(config, ChromaDBConfig):
        from maru_lang.core.vector_db.chroma import ChromaVectorDB
        return ChromaVectorDB(
            persist_dir=config.persist_dir,
            collection_name=config.collection_name,
        )

    # Pinecone (향후 확장)
    elif isinstance(config, PineconeConfig):
        # from maru_lang.core.vector_db.pinecone import PineconeVectorDB
        # return PineconeVectorDB(...)
        raise NotImplementedError("Pinecone support is not yet implemented")

    else:
        raise ValueError(f"Unsupported VectorDB config type: {type(config)}")
