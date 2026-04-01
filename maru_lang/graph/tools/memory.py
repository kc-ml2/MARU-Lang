"""Memory tools - 장기 기억 읽기/쓰기

개발 단계에서는 in-memory dict 사용.
추후 VectorDB memory collection으로 교체 예정.
"""
from datetime import datetime
from langchain_core.tools import tool

# In-memory store (개발용, 추후 VectorDB로 교체)
_memory_store: list[dict] = []


@tool
def memory_read(query: str) -> str:
    """이전 대화에서 저장된 기억을 검색합니다.
    사용자의 선호도, 이전에 논의한 내용, 중요한 컨텍스트를 떠올릴 때 사용하세요.

    Args:
        query: 검색할 키워드 또는 주제
    """
    if not _memory_store:
        return "저장된 기억이 없습니다."

    query_lower = query.lower()
    matches = []
    for mem in _memory_store:
        content_lower = mem["content"].lower()
        if any(word in content_lower for word in query_lower.split()):
            matches.append(mem)

    if not matches:
        return f"'{query}'와 관련된 기억을 찾지 못했습니다."

    formatted = []
    for mem in matches:
        formatted.append(
            f"[{mem['memory_type']}] ({mem['created_at']})\n{mem['content']}"
        )
    return "\n\n".join(formatted)


@tool
def memory_write(content: str, memory_type: str = "context") -> str:
    """대화에서 중요한 정보를 장기 기억에 저장합니다.
    사용자의 선호도, 중요한 결정사항, 나중에 참고할 내용을 기억할 때 사용하세요.

    Args:
        content: 기억할 내용
        memory_type: 기억 유형 - "fact" (사실), "preference" (선호도), "context" (맥락)
    """
    memory_entry = {
        "content": content,
        "memory_type": memory_type,
        "created_at": datetime.now().isoformat(),
    }
    _memory_store.append(memory_entry)
    return f"기억이 저장되었습니다: [{memory_type}] {content[:50]}..."


def get_memory_store() -> list[dict]:
    """테스트용: 현재 메모리 스토어 반환"""
    return _memory_store


def clear_memory_store():
    """테스트용: 메모리 초기화"""
    _memory_store.clear()
