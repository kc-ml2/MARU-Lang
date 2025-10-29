from enum import Enum


class ChatProcessStep(str, Enum):
    """채팅 처리 단계"""
    AGENT_SELECTION = "agent_selection"
    AGENT_EXECUTION = "agent_execution"
    ANSWER_GENERATION = "answer_generation"
    COMPLETED = "completed"