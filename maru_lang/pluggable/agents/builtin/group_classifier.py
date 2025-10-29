"""
Group Classifier Agent - Classifies user questions into appropriate document groups
"""
import json
from typing import Dict, Any, Optional, List
from maru_lang.pluggable.agents.base import BaseAgent, AgentResult
from maru_lang.configs.group_loader import GroupConfigLoader
from maru_lang.dependencies.langfuse import LangfuseContext
from maru_lang.tracing import safe_observe


class GroupClassifierAgent(BaseAgent):
    """Agent for classifying user questions into appropriate document groups"""

    def __init__(
        self,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.group_loader = GroupConfigLoader()
        self.available_groups = {}
        self.keyword_mappings = {}

    async def _setup(self) -> None:
        """Initialize group classification capabilities"""
        # Load group configurations
        self.group_loader.reload()
        self.available_groups = self.group_loader.all_groups

    @safe_observe(name="group_classifier_agent", as_type="generation")
    async def execute(
        self,
        question: str,
        metadata: Optional[Dict[str, Any]] = {},
        context: Optional[LangfuseContext] = None,
        **kwargs
    ) -> AgentResult:
        """
        Execute group classification

        Args:
            question: User question to classify
            metadata: Optional metadata for tracing
            **kwargs: Additional parameters

        Returns:
            AgentResult containing classified groups
        """
        forced_groups = metadata.get('forced_groups', None)
        if forced_groups:
            # check forced_groups is valid
            for group in forced_groups:
                if group not in self.available_groups:
                    # # TODO notify warning
                    pass


        # 자체적으로 관리하는 모든 그룹 사용
        if not self.available_groups:
            return AgentResult(
                success=True,
                result="",  # 주요 출력: 그룹 목록 문자열
                data={
                    'selected_groups': [],
                    'confidence': 0.1,
                    'reasoning': 'No document groups available'
                }
            )

        try:
            # 모든 사용 가능한 그룹으로 포맷
            available_groups_str = self._format_available_groups(forced_groups)
            if not available_groups_str:
                return AgentResult(
                    success=True,
                    result="",  # 주요 출력: 그룹 목록 문자열
                    data={
                        'selected_groups': [],
                        'confidence': 0.1,
                        'reasoning': 'No available groups provided'
                    }
                )

            classification_result = await self._classify_with_llm(
                question,
                available_groups_str,
            )

            # 모든 그룹 목록으로 검증
            processed_result = self._process_classification_result(
                classification_result,
                list(self.available_groups.keys())
            )

            selected_groups = processed_result.get('selected_groups', [])
            return AgentResult(
                success=True,
                result=', '.join(selected_groups),  # 주요 출력: 그룹 목록 문자열
                data=processed_result,
                metadata={
                    'classification_method': 'llm_with_tools',
                }
            )

        except Exception as e:
            # Fallback to default group on error
            return AgentResult(
                success=True,  # Still successful, but using fallback
                result="",  # 주요 출력: 빈 문자열
                data={
                    'selected_groups': [],
                    'confidence': 0.1,
                    'reasoning': f'Fallback due to error: {str(e)}',
                    'fallback_used': True
                },
                metadata={
                    'classification_method': 'fallback',
                    'error': str(e)
                }
            )

    def _format_available_groups(self, forced_groups: List[str] = None) -> str:
        """Format all available groups for LLM prompt"""
        group_descriptions = []
        for group_name, group_config in self.available_groups.items():
            if forced_groups and group_name not in forced_groups:
                continue
            desc = f"- {group_name}: {group_config.description}"
            group_descriptions.append(desc)

        return "\n".join(group_descriptions)

    async def _classify_with_llm(
        self,
        question: str,
        available_groups: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Use LLM for detailed group classification with fallback"""
        # Prepare tool definition
        tools = [
            tool.to_dict(tool_name=tool_name) for tool_name, tool in self.config.tools.items()
        ]

        prompts = self.config.prompts

        # 템플릿에 질문 삽입
        user_prompt = prompts.user_prompt_template.format(
            question=question,
            available_groups=available_groups
        )

        override_params = self.get_override_params()

        # Prepare messages for request_with_tools_and_fallback
        messages = [
            {"role": "system", "content": prompts.system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        # Make LLM request with automatic fallback
        response = await self.request_with_tools_and_fallback(
            messages=messages,
            tools=tools,
            tool_choice="auto",
            **override_params,
        )

        return response

    def _process_classification_result(
        self,
        result: Dict[str, Any],
        available_group_names: List[str]
    ) -> Dict[str, Any]:
        """Process and validate classification result"""
        classification_config = self.config.config.classification_config
        if not classification_config:
            max_groups = len(self.available_groups)
            confidence_threshold = 0.0
        else:
            max_groups = classification_config.max_groups
            confidence_threshold = classification_config.confidence_threshold

        # Extract arguments from tool_calls structure
        tool_calls = result.get('tool_calls', [])
        if tool_calls:
            # Get arguments from first tool call
            arguments = tool_calls[0].get('function', {}).get('arguments', {})
            # If arguments is a string, parse it
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
        else:
            # Fallback: assume result is already the arguments
            arguments = result

        # Extract and validate groups
        selected_groups = arguments.get('selected_groups', [])
        confidence = arguments.get('confidence', 0.0)
        reasoning = arguments.get('reasoning', 'No reasoning provided')

        # Validate groups exist in available_group_names (실제 전달된 그룹 목록)
        valid_groups = []
        invalid_groups = []

        for group in selected_groups[:max_groups]:
            # available_group_names가 있으면 그것을 기준으로, 없으면 self.available_groups 사용
            if group in available_group_names:
                valid_groups.append(group)
            else:
                invalid_groups.append(group)

        # 잘못된 그룹이 선택된 경우 reasoning에 추가
        if invalid_groups:
            reasoning += f" (잘못 선택된 그룹 제외됨: {', '.join(invalid_groups)})"

        # Check confidence threshold
        if confidence < confidence_threshold:
            valid_groups = []
            reasoning += f" (신뢰도 {confidence}가 임계값 {confidence_threshold}보다 낮음)"

        return {
            'selected_groups': valid_groups,
            'confidence': confidence,
            'reasoning': reasoning,
        }

    def get_available_groups(self) -> Dict[str, str]:
        """Get available groups with descriptions"""
        return {
            name: config.description
            for name, config in self.available_groups.items()
        }
