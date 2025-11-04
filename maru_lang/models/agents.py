"""
Agent-related data models
"""
import asyncio
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Union, TYPE_CHECKING
from maru_lang.enums.chat import ChatProcessStep as ChatStep
from maru_lang.models.chat import ChatHistory
from maru_lang.core.vector_db.retrieve_document import RetrieveDocument


@dataclass
class AgentResult:
    """Result from individual agent execution"""
    success: bool
    result: str = ""  # 주요 출력 결과 (표준화된 문자열)
    data: Optional[Dict[str, Any]] = None  # 추가 정보 (선택)
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def _serialize_value(self, value: Any) -> Any:
        """Recursively serialize values to JSON-compatible format"""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        elif isinstance(value, dict):
            return {k: self._serialize_value(v) for k, v in value.items()}
        elif isinstance(value, (list, tuple)):
            return [self._serialize_value(item) for item in value]
        elif hasattr(value, 'text'):
            # Handle MCP TextContent objects
            return value.text
        elif hasattr(value, 'to_dict'):
            return self._serialize_value(value.to_dict())
        elif hasattr(value, '__dict__'):
            return self._serialize_value(value.__dict__)
        else:
            # Fallback: convert to string
            return str(value)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with safe serialization"""
        return {
            "success": self.success,
            "result": self.result,
            "data": self._serialize_value(self.data),
            "error": self.error,
            "metadata": self._serialize_value(self.metadata)
        }


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
    chat_history: ChatHistory
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict)

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
    internal_documents: List[RetrieveDocument] = field(default_factory=list)


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


