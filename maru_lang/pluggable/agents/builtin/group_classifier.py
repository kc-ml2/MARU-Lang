"""Group Classifier Agent - Classifies user questions into appropriate document groups"""
import json
import asyncio
from typing import Dict, Any, Optional, List, Tuple
from maru_lang.configs import RagConfig
from maru_lang.models.agents import ExecutionContext
from maru_lang.pipelines.base import PipelineMessage
from maru_lang.pluggable.agents.base import BaseAgent, AgentResult
from maru_lang.configs.manager import get_config_manager
from maru_lang.services.document import get_document_group_descriptions
from maru_lang.utils.distribution import allocate_by_weight


class GroupClassifierAgent(BaseAgent):
    """Agent for classifying user questions into appropriate document groups"""

    def __init__(
        self,
        **kwargs,
    ):
        super().__init__(**kwargs)
        config_manager = get_config_manager()
        self.rag_config = config_manager.get_rag_config()
        self.embedder_config = config_manager.get_embedder_config()

    async def execute(
        self,
        context: ExecutionContext,
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
        # Set progress queue if provided
        try:

            # 모든 사용 가능한 그룹으로 포맷
            available_groups_str = await self._format_available_groups(context.accessible_groups)
            if not available_groups_str:
                return AgentResult(
                    status="error",
                    error="No available groups provided for classification."
                )

            classification_result = await self._classify_with_llm(
                context.question,
                available_groups_str,
            )

            selected_groups, confidence, reasoning, group_confidences = self._parse_classification_result(
                classification_result)
            if not selected_groups:
                return AgentResult(
                    status="success",
                    payload={
                        'selected_groups': {},
                        "confidence": confidence,
                        "reasoning": reasoning
                    }
                )

            group_with_weights_str = [f"{group_name}: {group_confidence}" for group_name, group_confidence in zip(
                selected_groups, group_confidences)]
            selected_group_message = f"Group Classifier: Selected groups: {group_with_weights_str}"
            await context.progress_queue.put(
                PipelineMessage.debug(selected_group_message)
            )
            await context.progress_queue.put(
                PipelineMessage.debug(
                    f"Group Classifier: Confidence: {confidence} and threshold: {self._get_confidence_threshold()}")
            )
            # 2) 길이 보정 + 타입/음수 방어
            safe_confidences = []
            for v in group_confidences:
                try:
                    fv = float(v)
                    if fv < 0:
                        fv = 0.0
                except (TypeError, ValueError):
                    fv = 0.0
                safe_confidences.append(fv)

            if len(selected_groups) != len(safe_confidences):
                safe_confidences = (
                    safe_confidences[:len(selected_groups)]
                    + [0.0] * max(0, len(selected_groups) -
                                  len(safe_confidences))
                )

            # 3) 합 0 방지 + 정규화
            total = sum(safe_confidences)
            if total <= 0:
                # 점수가 전부 0이면 우선 균등분포
                safe_confidences = [
                    1.0 / len(selected_groups)] * len(selected_groups)
            else:
                safe_confidences = [v / total for v in safe_confidences]

            # 4) 전체 신뢰도 임계치 체크
            if confidence < self._get_confidence_threshold():
                # 전반 신뢰도가 낮으면 균등분포로 ‘내려앉기’
                normalized_scores: Dict[str, float] = {
                    group: 1.0 / len(selected_groups) for group in selected_groups
                }
                normalized_scores = {
                    group: 1.0 if group == selected_groups[0] else 0.0 for group in selected_groups
                }
                # 전반 신뢰가 낮으면 가장 높은 [1]번 그룹을 1로 선택 나머지는 0으로 선택
                await context.progress_queue.put(
                    PipelineMessage.debug(
                        "Confidence is too low, selected the highest confidence group and set the rest to 0")
                )
                return AgentResult(
                    status="success",
                    payload={
                        'selected_groups': self._group_result_package(selected_groups, list(normalized_scores.values())),
                        'confidence': confidence,
                        'reasoning': reasoning + 'Confidence is too low',
                    }
                )

            # 5) 신뢰도 충분: 정규화한 점수 사용
            return AgentResult(
                status="success",
                payload={
                    'selected_groups': self._group_result_package(selected_groups, safe_confidences),
                    'confidence': confidence,
                    'reasoning': reasoning,
                })

        except Exception as e:
            # Fallback to default group on error
            return AgentResult(
                status="error",
                error=f"Fallback due to error: {str(e)}"
            )

    async def _format_available_groups(self, accessible_groups: List[str]) -> str:
        """Format all available groups for LLM prompt"""

        # 1. Get descriptions from DocumentGroup DB (only non-null descriptions)
        group_descriptions_dict = {}
        if accessible_groups:
            db_descriptions = await get_document_group_descriptions(accessible_groups)
            group_descriptions_dict.update(db_descriptions)

        # 2. Override with rag_config.groups descriptions if available
        for group_name, group_config in self.rag_config.groups.items():
            if accessible_groups and group_name not in accessible_groups:
                continue
            if group_config.description:
                # Override DB description with config description
                group_descriptions_dict[group_name] = group_config.description
            elif group_name not in group_descriptions_dict:
                # No description in both DB and config
                group_descriptions_dict[group_name] = 'No description provided.'

        # 3. Format as list
        group_descriptions = [
            f"- {group_name}: {description}"
            for group_name, description in group_descriptions_dict.items()
        ]
        return "\n".join(group_descriptions)

    def _group_result_package(
        self,
        gruop_names: list[str],
        group_confidences: list[float],
    ):

        allocated_results = allocate_by_weight(
            groups_with_weights=[(group_name, group_confidence) for group_name,
                                 group_confidence in zip(gruop_names, group_confidences)],
            max_results=self.rag_config.retriever.default_k,
        )
        return {
            group_name: {
                'embedding_model': self._get_embedding_model(group_name),
                'retrieval_count': allocated_results[group_name],
            }
            for group_name in gruop_names
        }

    def _parse_classification_result(self, result: Dict[str, Any]) -> Tuple[List[str], float, str, List[float]]:

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
        group_confidences = arguments.get('group_confidences', [])

        return selected_groups, confidence, reasoning, group_confidences

    async def _classify_with_llm(
        self,
        question: str,
        available_groups: str,
    ) -> Dict[str, Any]:
        """Use LLM for detailed group classification with fallback"""
        # Prepare tool definition
        tools = [
            tool.to_dict(tool_name=tool_name) for tool_name, tool in self.config.tools.items()
        ]
        prompts = self.config.prompts
        if prompts is None:
            raise ValueError(
                "Prompts configuration is missing in GroupClassifierAgent")

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

    def _get_confidence_threshold(self) -> float:
        """Retrieve confidence threshold from configuration with fallback"""
        if self.config.config is None:
            return 0.5
        classification_config = self.config.config.classification_config
        if not classification_config:
            return 0.5
        threshold = classification_config.confidence_threshold
        return float(threshold)

    def _get_embedding_model(self, group_name: Optional[str] = None) -> str:
        """Get embedding model from configuration"""
        if group_name:
            group_config = self.rag_config.groups.get(group_name, None)
            if group_config and group_config.components and group_config.components.embedding_model:
                return group_config.components.embedding_model

        # Fallback to default model
        if self.embedder_config and self.embedder_config.default_model:
            return self.embedder_config.default_model

        # Last resort fallback
        raise ValueError(
            f"No embedding model configured for group '{group_name}' and no default model available. "
            "Please configure default_model in embedder_config.yaml"
        )
