"""
Agent configuration models
"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Union
from maru_lang.enums.agents import LLMFallbackStrategy


@dataclass
class SelectionCriteria:
    """Agent selection criteria"""
    keywords: List[str] = field(default_factory=list)
    patterns: List[str] = field(default_factory=list)
    internal_only: bool = False


@dataclass
class LLMOverrideParams:
    """LLM override parameters"""
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    timeout: Optional[float] = None


@dataclass
class TargetLLMConfig:
    """LLM configuration"""
    server_name: Optional[str] = None
    override_params: Optional[LLMOverrideParams] = None
    fallback_strategy: LLMFallbackStrategy = LLMFallbackStrategy.ANY_AVAILABLE

    def __post_init__(self):
        if isinstance(self.override_params, dict):
            self.override_params = LLMOverrideParams(**self.override_params)


@dataclass
class PromptsConfig:
    """Prompts configuration"""
    system_prompt: str = ""
    user_prompt_template: str = ""


@dataclass
class ClassificationConfig:
    """Classification configuration for group_classifier"""
    max_groups: int = 2
    confidence_threshold: float = 0.7


@dataclass
class ExtractionConfig:
    """Extraction configuration for intent/keyword extractors"""
    max_question_length: Optional[int] = None
    preserve_key_terms: Optional[bool] = None
    remove_emotions: Optional[bool] = None
    optimize_for_search: Optional[bool] = None
    min_keywords: Optional[int] = None
    max_keywords: Optional[int] = None
    filter_stopwords: Optional[bool] = None
    include_synonyms: Optional[bool] = None
    stopwords: List[str] = field(default_factory=list)


@dataclass
class ToolParameterProperty:
    """Tool parameter property"""
    type: str
    description: str = ""
    items: Optional[Dict[str, Any]] = None
    minimum: Optional[Union[int, float]] = None
    maximum: Optional[Union[int, float]] = None
    maxItems: Optional[int] = None


@dataclass
class ToolParameters:
    """Tool parameters schema"""
    type: str
    properties: Dict[str, ToolParameterProperty] = field(default_factory=dict)
    required: List[str] = field(default_factory=list)

    def __post_init__(self):
        new_props = {}
        for key, value in self.properties.items():
            if isinstance(value, dict):
                new_props[key] = ToolParameterProperty(**value)
            else:
                new_props[key] = value
        self.properties = new_props


@dataclass
class ToolConfig:
    """Tool configuration"""
    description: str
    parameters: Optional[ToolParameters] = None
    type: str = "function"  # Default to "function" for OpenAI API compatibility

    def __post_init__(self):
        if isinstance(self.parameters, dict):
            self.parameters = ToolParameters(**self.parameters)

    def to_dict(self, tool_name: str = "tool") -> Dict[str, Any]:
        """Convert ToolConfig to dictionary"""
        function_def = {
            "name": tool_name,
            "description": self.description
        }

        if self.parameters is not None:
            function_def["parameters"] = {
                "type": self.parameters.type,
                "properties": {
                    key: {
                        "type": prop.type,
                        "description": prop.description,
                        **({"items": prop.items} if prop.items is not None else {}),
                        **({"minimum": prop.minimum} if prop.minimum is not None else {}),
                        **({"maximum": prop.maximum} if prop.maximum is not None else {}),
                        **({"maxItems": prop.maxItems} if prop.maxItems is not None else {}),
                    }
                    for key, prop in self.parameters.properties.items()
                },
                "required": self.parameters.required
            }

        return {
            "type": self.type,
            "function": function_def
        }


@dataclass
class FormattingConfig:
    """Formatting configuration for response_agent"""
    include_metadata: bool = False
    show_sources: bool = True
    use_markdown: bool = True


@dataclass
class ScenarioConfig:
    """Scenario-specific configuration for response_agent"""
    no_agents: str = "어떤 에이전트도 선택되지 않았습니다. 사용자에게 더 구체적인 질문을 요청하거나 일반적인 도움을 제공하세요."
    errors: str = "에이전트 실행 중 오류가 발생했습니다. 사용자에게 오류를 친절하게 설명하고 재시도를 제안하세요."
    success: str = "에이전트가 성공적으로 실행되었습니다. 결과를 사용자 친화적으로 전달하세요."
    partial_success: str = "일부 에이전트는 성공했지만 일부는 실패했습니다. 성공한 결과를 우선 전달하고 실패한 부분은 간략히 언급하세요."
    unknown: str = "알 수 없는 상황입니다. 사용자에게 도움을 제공하기 어렵다는 점을 친절하게 안내하세요."


@dataclass
class FallbackConfig:
    """Fallback responses when LLM is not available"""
    no_agents: str = "죄송합니다. 질문을 처리할 수 있는 적절한 에이전트를 찾지 못했습니다. 더 구체적으로 질문해주시겠어요?"
    errors: str = "죄송합니다. 요청을 처리하는 중 오류가 발생했습니다."
    success: str = ""  # Use formatted context as-is
    partial_success: str = ""  # Use formatted context as-is
    unknown: str = "죄송합니다. 답변을 생성할 수 없습니다."


@dataclass
class AgentGeneralConfig:
    """General agent configuration"""
    timeout: int = 30
    retry_count: int = 2
    max_context_length: Optional[int] = None
    classification_config: Optional[ClassificationConfig] = None
    extraction_config: Optional[ExtractionConfig] = None
    formatting: Optional[FormattingConfig] = None
    scenario_config: Optional[ScenarioConfig] = None
    fallback_config: Optional[FallbackConfig] = None

    def __post_init__(self):
        if isinstance(self.classification_config, dict):
            self.classification_config = ClassificationConfig(
                **self.classification_config)
        if isinstance(self.extraction_config, dict):
            self.extraction_config = ExtractionConfig(**self.extraction_config)
        if isinstance(self.formatting, dict):
            self.formatting = FormattingConfig(**self.formatting)
        if isinstance(self.scenario_config, dict):
            self.scenario_config = ScenarioConfig(**self.scenario_config)
        if isinstance(self.fallback_config, dict):
            self.fallback_config = FallbackConfig(**self.fallback_config)


@dataclass
class MCPConfig:
    """MCP configuration"""
    transport: str = "stdio"
    command: List[str] = field(default_factory=list)
    args: List[str] = field(default_factory=list)
    env: Dict[str, Any] = field(default_factory=dict)
    timeout: int = 30


@dataclass
class AgentConfig:
    """Agent configuration"""
    name: str
    description: str = ""
    type: str = ""
    enabled: bool = True
    version: str = "1.0.0"
    priority: int = 1
    selection_criteria: Optional[SelectionCriteria] = None
    target_llm_config: Optional[TargetLLMConfig] = None
    prompts: Optional[PromptsConfig] = None
    config: Optional[AgentGeneralConfig] = None
    tools: Dict[str, ToolConfig] = field(default_factory=dict)
    permissions: List[str] = field(default_factory=list)
    implementation: Optional[str] = None
    mcp_config: Optional[MCPConfig] = None
    source_path: str = ""
    is_override: bool = False
    examples: List[str] = field(default_factory=list)
    use_response_agent: bool = True

    def __post_init__(self):
        """Post-process configuration"""
        if isinstance(self.selection_criteria, dict):
            self.selection_criteria = SelectionCriteria(
                **self.selection_criteria)

        if isinstance(self.target_llm_config, dict):
            self.target_llm_config = TargetLLMConfig(**self.target_llm_config)

        if isinstance(self.prompts, dict):
            self.prompts = PromptsConfig(**self.prompts)

        if isinstance(self.config, dict):
            self.config = AgentGeneralConfig(**self.config)

        if isinstance(self.mcp_config, dict):
            self.mcp_config = MCPConfig(**self.mcp_config)

        new_tools = {}
        for key, value in self.tools.items():
            if isinstance(value, dict):
                new_tools[key] = ToolConfig(**value)
            else:
                new_tools[key] = value
        self.tools = new_tools

        if self.target_llm_config:
            try:
                fallback_strategy = self.target_llm_config.fallback_strategy
                self.target_llm_config.fallback_strategy = LLMFallbackStrategy(
                    fallback_strategy)
            except ValueError:
                print(
                    f"Warning: Invalid fallback strategy '{fallback_strategy}' in agent {self.name}, using 'any_available'")
                self.target_llm_config.fallback_strategy = LLMFallbackStrategy.ANY_AVAILABLE
