"""
Agent-related data models
"""
import asyncio
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from maru_lang.models.chat import ChatHistory
from maru_lang.core.vector_db.retrieve_document import RetrieveDocument


@dataclass
class AgentResult:
    """Result from individual agent execution"""
    status: str
    payload: Optional[Any] = None
    error: Optional[str] = None


@dataclass
class AgentSelection:
    """Result of agent selection process"""
    selected_agents: List[str]
    execution_order: List[str]
    reasoning: str
    parameters: Optional[Dict[str, Any]] = None
    fallback_config: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "selected_agents": self.selected_agents,
            "execution_order": self.execution_order,
            "reasoning": self.reasoning,
            "parameters": self.parameters or {},
            "fallback_config": self.fallback_config
        }


@dataclass
class ExecutionContext:
    """Context of agent execution"""
    question: str
    progress_queue: asyncio.Queue
    agent_selection: AgentSelection
    agent_results: Dict[str, AgentResult] = field(default_factory=dict)
    team_ids: List[int] = field(default_factory=list)
    team_names: List[str] = field(default_factory=list)
    accessible_groups: List[str] = field(default_factory=list)
    chat_history: Optional[ChatHistory] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    retrieved_documents: List[RetrieveDocument] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        # exclude progress_queue
        return {
            "question": self.question,
            "progress_queue": self.progress_queue,
            "chat_history": self.chat_history,
            "metadata": self.metadata
        }


