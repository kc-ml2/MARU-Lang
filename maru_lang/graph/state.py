"""ChatState - LangGraph 상태 스키마"""
from typing import Annotated, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class ChatState(TypedDict):
    """ReAct 에이전트의 공유 상태

    messages: 대화 히스토리 (LangGraph add_messages reducer로 자동 누적)
    team_ids: 팀 기반 접근 제어
    team_names: 팀 이름 목록
    accessible_groups: 접근 가능한 문서 그룹
    retrieved_documents: RAG로 검색된 문서 목록
    """
    messages: Annotated[list[BaseMessage], add_messages]
    team_ids: list[int]
    team_names: list[str]
    accessible_groups: list[str]
    retrieved_documents: list[dict]
