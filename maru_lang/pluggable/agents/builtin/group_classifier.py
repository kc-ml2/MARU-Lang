"""Group Classifier Agent - Classifies user questions into appropriate document groups"""
import json
from typing import Dict, Any, Optional, List
from maru_lang.pluggable.agents.base import BaseAgent, AgentResult
from maru_lang.configs.manager import get_config_manager
from maru_lang.dependencies.langfuse import LangfuseContext
from maru_lang.tracing import safe_observe


class GroupClassifierAgent(BaseAgent):
    """Agent for classifying user questions into appropriate document groups"""

    def __init__(
        self,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.available_groups: Dict[str, Any] = {}
        self.keyword_mappings = {}

    async def _setup(self) -> None:
        """Initialize group classification capabilities"""
        config_manager = get_config_manager()
        config_manager.ensure_loaded()

        rag_loader = getattr(config_manager, "rag_loader", None)

        if not rag_loader:
            print("⚠️  RagConfig loader is not available; no document groups loaded")
            self.available_groups = {}
            self.base_group_weights = {}
            return

        # Ensure groups are loaded from rag configuration
        if not getattr(rag_loader, "all_groups", None):
            rag_loader.reload()

        rag_groups = getattr(rag_loader, "all_groups", {}) or {}
        self.available_groups = dict(rag_groups)

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


        # Use the complete set of managed groups
        if not self.available_groups:
            return AgentResult(
                success=True,
                result="",
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
                    result="",
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
                result=', '.join(selected_groups),
                data=processed_result,
                metadata={
                    'classification_method': 'llm_with_tools',
                }
            )

        except Exception as e:
            # Fallback to default group on error
            return AgentResult(
                success=True,
                result="",
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
            description = getattr(group_config, 'description', '') or 'No description provided.'
            desc = f"- {group_name}: {description}"
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
        group_scores_raw = arguments.get('group_confidences') or arguments.get('group_scores')

        normalized_scores: Dict[str, float] = {}

        # Case 1: LLM returns list of confidences aligned with selected_groups
        if isinstance(group_scores_raw, list) and selected_groups:
            confidences_list = []
            try:
                confidences_list = [float(score) for score in group_scores_raw]
            except (TypeError, ValueError):
                confidences_list = []

            if len(confidences_list) != len(selected_groups):
                # Length mismatch: pad or trim to match selected_groups
                confidences_list = (
                    confidences_list[:len(selected_groups)]
                    + [0.0] * max(0, len(selected_groups) - len(confidences_list))
                )

            # Map confidences to corresponding selected groups
            for group_name, score in zip(selected_groups, confidences_list):
                if group_name in available_group_names:
                    normalized_scores[group_name] = max(float(score), 0.0)

        # Case 2: dictionary input (fallback for older format)
        elif isinstance(group_scores_raw, dict):
            for group_name, score in group_scores_raw.items():
                try:
                    normalized_scores[group_name] = max(float(score), 0.0)
                except (TypeError, ValueError):
                    normalized_scores[group_name] = 0.0

        # Ensure every available group has a score (default 0)
        normalized_scores = {
            group_name: normalized_scores.get(group_name, 0.0)
            for group_name in available_group_names
        }

        total_score = sum(normalized_scores.values())
        if total_score > 0:
            normalized_scores = {
                group: score / total_score for group, score in normalized_scores.items()
            }
        elif normalized_scores:
            equal_score = 1.0 / len(normalized_scores)
            normalized_scores = {group: equal_score for group in normalized_scores}

        # Determine priority order (respect LLM-selected order)
        prioritized_groups: List[str] = []
        seen = set()
        for group in selected_groups:
            if group not in seen:
                prioritized_groups.append(group)
                seen.add(group)

        # Then, add remaining groups by descending normalized score
        for group, _ in sorted(
            normalized_scores.items(), key=lambda item: item[1], reverse=True
        ):
            if group not in seen:
                prioritized_groups.append(group)
                seen.add(group)

        valid_groups: List[str] = []
        invalid_groups: List[str] = []
        for group in prioritized_groups:
            if group not in available_group_names:
                invalid_groups.append(group)
                continue
            if normalized_scores.get(group, 0.0) > 0:
                valid_groups.append(group)

        if invalid_groups:
            reasoning += f" (Excluded invalid groups: {', '.join(invalid_groups)})"

        return {
            'selected_groups': valid_groups,
            'confidence': confidence,
            'group_confidences': normalized_scores,
            'group_weights': normalized_scores,
            'reasoning': reasoning,
        }

    def get_available_groups(self) -> Dict[str, str]:
        """Get available groups with descriptions"""
        return {
            name: config.description
            for name, config in self.available_groups.items()
        }
