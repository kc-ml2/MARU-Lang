"""
RAG configuration models
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple


@dataclass
class QueryTypeWeights:
    """Query type별 가중치 설정"""
    cosine_weight: float
    bm25_weight: float

    def to_tuple(self) -> Tuple[float, float]:
        """튜플로 변환"""
        return (self.cosine_weight, self.bm25_weight)


@dataclass
class FallbackWeights:
    """Fallback 시나리오별 가중치"""
    cosine_weight: float
    bm25_weight: float

    def to_tuple(self) -> Tuple[float, float]:
        """튜플로 변환"""
        return (self.cosine_weight, self.bm25_weight)


@dataclass
class FallbackLogicConfig:
    """Fallback 로직 설정"""
    similarity_threshold: float = 0.3  # 이 값 이하면 fallback 사용
    short_query_length: int = 2        # 짧은 쿼리 기준
    long_query_length: int = 6         # 긴 쿼리 기준
    weights: Dict[str, FallbackWeights] = field(default_factory=dict)  # short_query, medium_query, long_query

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FallbackLogicConfig':
        """딕셔너리로부터 생성"""
        weights = {}
        if 'weights' in data:
            for key, value in data['weights'].items():
                weights[key] = FallbackWeights(
                    cosine_weight=value.get('cosine_weight', 0.5),
                    bm25_weight=value.get('bm25_weight', 0.5),
                )

        return cls(
            similarity_threshold=data.get('similarity_threshold', 0.3),
            short_query_length=data.get('short_query_length', 2),
            long_query_length=data.get('long_query_length', 6),
            weights=weights,
        )


@dataclass
class RetrieverConfig:
    """Retriever 전역 설정"""
    default_k: int = 5
    default_method: str = "vector"  # vector, bm25, ensemble
    search_on_empty_groups: bool = True
    query_type_weights: Dict[str, QueryTypeWeights] = field(default_factory=dict)
    representative_queries: Dict[str, str] = field(default_factory=dict)
    fallback_logic: Optional[FallbackLogicConfig] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RetrieverConfig':
        """딕셔너리로부터 생성"""
        query_type_weights = {}
        if 'query_type_weights' in data:
            for query_type, weights in data['query_type_weights'].items():
                query_type_weights[query_type] = QueryTypeWeights(
                    cosine_weight=weights.get('cosine_weight', 0.5),
                    bm25_weight=weights.get('bm25_weight', 0.5),
                )

        fallback_logic = None
        if 'fallback_logic' in data:
            fallback_logic = FallbackLogicConfig.from_dict(data['fallback_logic'])

        return cls(
            default_k=data.get('default_k', 5),
            default_method=data.get('default_method', 'vector'),
            search_on_empty_groups=data.get('search_on_empty_groups', True),
            query_type_weights=query_type_weights,
            representative_queries=data.get('representative_queries', {}),
            fallback_logic=fallback_logic,
        )


@dataclass
class GroupComponents:
    """그룹별 플러거블 컴포넌트 설정"""
    loader: Optional[str] = None
    chunker: Optional[str] = None
    embedding_model: Optional[str] = None


@dataclass
class GroupRagConfig:
    """그룹별 RAG 설정"""
    name: str
    description: str = ""

    # 플러거블 컴포넌트 설정 (선택사항)
    # 이 그룹에서만 다른 컴포넌트를 사용하고 싶을 때 설정
    components: Optional[GroupComponents] = None

    # 메타데이터
    source_path: str = ""
    is_override: bool = False

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any], source_path: str = "", is_override: bool = False) -> 'GroupRagConfig':
        """딕셔너리로부터 생성"""
        # Components
        components = None
        if 'components' in data:
            components = GroupComponents(
                loader=data['components'].get('loader'),
                chunker=data['components'].get('chunker'),
                embedding_model=data['components'].get('embedding_model'),
            )

        return cls(
            name=name,
            description=data.get('description', ''),
            components=components,
            source_path=source_path,
            is_override=is_override,
        )


@dataclass
class RagConfig:
    """전체 RAG 설정"""
    # Retriever 전역 설정
    retriever: RetrieverConfig = field(default_factory=RetrieverConfig)

    # 그룹별 RAG 설정
    groups: Dict[str, GroupRagConfig] = field(default_factory=dict)

    # 메타데이터
    source_path: str = ""
    is_override: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any], source_path: str = "", is_override: bool = False) -> 'RagConfig':
        """딕셔너리로부터 생성"""
        # Retriever config
        retriever = RetrieverConfig.from_dict(data.get('retriever', {}))

        # Groups
        groups = {}
        raw_groups = data.get('groups') or {}
        if not isinstance(raw_groups, dict):
            raw_groups = {}

        for group_name, group_data in raw_groups.items():
            groups[group_name] = GroupRagConfig.from_dict(
                name=group_name,
                data=group_data,
                source_path=source_path,
                is_override=is_override,
            )

        return cls(
            retriever=retriever,
            groups=groups,
            source_path=source_path,
            is_override=is_override,
        )
