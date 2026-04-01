"""더미 knowledge_search tool - 개발/테스트용"""
from langchain_core.tools import tool

DUMMY_DOCUMENTS = [
    {
        "id": "doc_001",
        "title": "MARU 프로젝트 개요",
        "content": "MARU는 LLM 기반 RAG 시스템으로, 기업용 문서 검색 및 질의응답을 지원합니다. "
                   "멀티 에이전트 아키텍처를 사용하며, 한국어 자연어 처리에 특화되어 있습니다.",
        "group": "general",
        "score": 0.95,
    },
    {
        "id": "doc_002",
        "title": "RAG 파이프라인 구조",
        "content": "문서 인제스트 파이프라인은 Loader → Chunker → Embedder → VectorDB 순서로 처리됩니다. "
                   "Loader는 PDF, DOCX, TXT 등 다양한 포맷을 지원하고, "
                   "Chunker는 paragraph, sentence, fixed-size 전략을 제공합니다.",
        "group": "technical",
        "score": 0.88,
    },
    {
        "id": "doc_003",
        "title": "팀 권한 관리",
        "content": "각 팀은 자신에게 할당된 문서 그룹에만 접근 가능합니다. "
                   "team_ids를 기반으로 접근 제어가 이루어지며, "
                   "관리자는 모든 문서에 접근할 수 있습니다.",
        "group": "admin",
        "score": 0.82,
    },
    {
        "id": "doc_004",
        "title": "LangGraph 마이그레이션 계획",
        "content": "기존 커스텀 파이프라인을 LangGraph ReAct 패턴으로 전환합니다. "
                   "AgentSelector를 제거하고 LLM이 직접 tool을 호출하는 구조로 변경합니다. "
                   "Memory는 별도 tool로 구현하여 장기 기억을 지원합니다.",
        "group": "technical",
        "score": 0.79,
    },
]


@tool
def knowledge_search(query: str, search_method: str = "hybrid") -> str:
    """팀 문서에서 관련 정보를 검색합니다.
    사용자 질문에 답하기 위해 내부 문서를 검색할 때 사용하세요.

    Args:
        query: 검색할 질문 또는 키워드
        search_method: 검색 방법 ("vector", "hybrid"). 기본값은 "hybrid"
    """
    # 더미: query 키워드와 매칭되는 문서 반환
    query_lower = query.lower()
    results = []
    for doc in DUMMY_DOCUMENTS:
        text = f"{doc['title']} {doc['content']}".lower()
        if any(word in text for word in query_lower.split()):
            results.append(doc)

    if not results:
        results = DUMMY_DOCUMENTS[:2]

    formatted = []
    for doc in results:
        formatted.append(
            f"[{doc['id']}] {doc['title']} (score: {doc['score']})\n"
            f"{doc['content']}"
        )
    return "\n\n---\n\n".join(formatted)
