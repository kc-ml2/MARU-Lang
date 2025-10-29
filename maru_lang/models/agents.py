"""
Agent-related data models
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Union, TYPE_CHECKING
from maru_lang.enums.chat import ChatProcessStep as ChatStep
from maru_lang.models.chat import ChatHistory

if TYPE_CHECKING:
    from maru_lang.core.vector_db.retrieve_document import RetrieveDocument


@dataclass
class AgentResult:
    """Result from individual agent execution"""
    success: bool
    result: str = ""  # 주요 출력 결과 (표준화된 문자열)
    data: Optional[Dict[str, Any]] = None  # 추가 정보 (선택)
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "success": self.success,
            "result": self.result,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata
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
    chat_history: ChatHistory
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "question": self.question,
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
    pass
    # answer: str
    # agents_used: List[str]
    # execution_details: Dict[str, Any]
    # documents: Optional[List[Any]] = None
    # metadata: Optional[Dict[str, Any]] = None

    # def to_dict(self) -> Dict[str, Any]:
    #     """Convert to dictionary"""
    #     return {
    #         "answer": self.answer,
    #         "agents_used": self.agents_used,
    #         "execution_details": self.execution_details,
    #         "documents": self.documents,
    #         "metadata": self.metadata
    #     }


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


@dataclass
class WebSearchResult:
    """Result from web search"""
    title: str
    url: str
    content: str
    snippet: str = ""
    relevance_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "title": self.title,
            "url": self.url,
            "content": self.content,
            "snippet": self.snippet,
            "relevance_score": self.relevance_score,
            "metadata": self.metadata
        }


