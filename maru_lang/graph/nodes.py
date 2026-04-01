"""LangGraph 노드 정의 - agent node"""
from langchain_core.messages import SystemMessage
from langgraph.graph import MessagesState

from maru_lang.graph.state import ChatState

SYSTEM_PROMPT = """당신은 MARU 팀 문서 기반 AI 어시스턴트입니다.

## 역할
사용자의 질문에 대해 팀 내부 문서를 검색하고, 정확한 정보를 바탕으로 답변합니다.

## 사용 가능한 도구
- knowledge_search: 팀 문서에서 관련 정보를 검색합니다. 사용자가 문서 관련 질문을 하면 반드시 이 도구를 사용하세요.
- memory_read: 이전 대화에서 저장한 기억을 검색합니다. 사용자가 이전에 논의한 내용을 물어보면 사용하세요.
- memory_write: 중요한 정보를 장기 기억에 저장합니다. 사용자의 선호도나 중요한 결정사항이 있으면 저장하세요.

## 규칙
1. 문서 검색 결과를 기반으로 답변하세요. 검색 결과가 없으면 솔직히 모른다고 말하세요.
2. 한국어로 답변하세요.
3. 답변에 출처 문서 ID를 포함하세요 (예: [doc_001]).
4. 사용자가 중요한 선호도나 결정을 언급하면 memory_write로 저장하세요.
"""


def make_agent_node(model):
    """agent node 팩토리 - LLM 모델을 받아서 노드 함수 반환"""

    async def agent_node(state: ChatState):
        messages = state["messages"]

        # system prompt가 없으면 맨 앞에 추가
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)

        response = await model.ainvoke(messages)
        return {"messages": [response]}

    return agent_node
