"""
Agent-related data models
"""
import asyncio
from dataclasses import dataclass, field
from typing import AsyncGenerator, List, Dict, Any, Optional, Union, TYPE_CHECKING
from maru_lang.enums.chat import ChatProcessStep as ChatStep
from maru_lang.models.chat import ChatHistory
from maru_lang.core.vector_db.retrieve_document import RetrieveDocument
from maru_lang.schemas.chat import DocumentReference


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


@dataclass
class ExecutionResult:
    """Result of agent execution orchestration"""
    agent_results: Dict[str, AgentResult]
    execution_order: List[str]

    success: bool
    errors: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "agent_results": {
                name: result.to_dict()
                for name, result in self.agent_results.items()
            },
            "execution_order": self.execution_order,
            "success": self.success,
            "errors": self.errors
        }


@dataclass
class ChatResult:
    """Final chat processing result"""
    answer: str
    internal_documents: List[DocumentReference] = field(default_factory=list)


@dataclass
class ChatProcess:
    """Chat processing result"""
    step: ChatStep
    data: Union[AgentSelection, ExecutionResult, str, ChatResult]


@dataclass
class GenerateAnswerResult:
    """Result from answer generation"""
    answer: str
    documents: List[Any] = field(default_factory=list)
    success: bool = True
    confidence: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None
