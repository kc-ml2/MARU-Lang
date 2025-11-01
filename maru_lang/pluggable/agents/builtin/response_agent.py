"""
Response Agent - Formats and delivers final responses to users
다른 에이전트들의 결과를 받아서 사용자 친화적으로 포맷팅하여 전달하는 에이전트
"""
from typing import Dict, Any, Optional
from maru_lang.pluggable.agents.base import BaseAgent, AgentResult


class ResponseAgent(BaseAgent):
    """
    최종 응답을 생성하고 포맷팅하는 에이전트
    다른 에이전트의 실행 결과를 받아서 사용자에게 친절하게 전달
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def _setup(self) -> None:
        """Initialize response agent settings - validates required config"""
        if not self.config.config:
            raise ValueError("Response agent requires 'config' section in YAML")
        if not self.config.config.formatting:
            raise ValueError("Response agent requires 'config.formatting' in YAML")
        if not self.config.config.scenario_config:
            raise ValueError("Response agent requires 'config.scenario_config' in YAML")
        if not self.config.config.fallback_config:
            raise ValueError("Response agent requires 'config.fallback_config' in YAML")

    async def execute(
        self,
        question: str,
        execution_result=None,
        selection=None,
        chat_history=None,
        **kwargs
    ) -> AgentResult:
        """
        Execute response formatting and generation
        Handles all execution scenarios:
        - No agents selected (execution_result is None)
        - Agent execution errors (execution_result.errors)
        - Successful agent results (execution_result.agent_results)

        Args:
            question: 사용자의 원본 질문
            execution_result: 에이전트 실행 결과 (None, errors, agent_results 등)
            selection: AgentSelection result
            chat_history: Chat history
            **kwargs: 추가 파라미터

        Returns:
            AgentResult with formatted response
        """
        try:
            # Step 1: Analyze execution result and determine scenario
            scenario, formatted_context = self._analyze_execution_result(
                execution_result, selection
            )

            # Step 2: Generate user-friendly response using LLM based on scenario
            final_response = await self._generate_final_response(
                question, formatted_context, scenario
            )

            # Step 3: Apply post-processing if needed
            max_length = self.config.config.formatting.max_response_length
            if max_length > 0:
                final_response = self._truncate_response(
                    final_response, max_length
                )

            return AgentResult(
                success=True,
                result=final_response,  # 주요 응답 텍스트
                data={
                    "scenario": scenario,
                    "formatted_context": formatted_context if self.config.config.formatting.include_metadata else None,
                }
            )

        except Exception as e:
            return AgentResult(
                success=False,
                result="",
                error=f"Response formatting failed: {str(e)}"
            )

    def _analyze_execution_result(
        self,
        execution_result,
        selection
    ) -> tuple[str, str]:
        """
        Analyze execution result and determine scenario

        Args:
            execution_result: 에이전트 실행 결과
            selection: AgentSelection result

        Returns:
            Tuple of (scenario, formatted_context)
            scenario: "no_agents", "errors", "success", "partial_success"
            formatted_context: Formatted string with relevant context
        """
        # Scenario 1: No agents selected
        if execution_result is None:
            return "no_agents", "선택된 에이전트가 없습니다."

        # Scenario 2: Only errors (no successful results)
        if execution_result.errors and not execution_result.agent_results:
            error_msg = "\n".join(
                [f"- {agent}: {error}" for agent, error in execution_result.errors.items()]
            )
            return "errors", f"에이전트 실행 중 오류 발생:\n{error_msg}"

        # Scenario 3: Successful results (with or without some errors)
        if execution_result.agent_results:
            formatted_results = self._format_agent_results(execution_result.agent_results)

            # Check if there are some errors along with successes
            if execution_result.errors:
                error_msg = "\n".join(
                    [f"- {agent}: {error}" for agent, error in execution_result.errors.items()]
                )
                formatted_results += f"\n\n일부 에이전트 실행 실패:\n{error_msg}"
                return "partial_success", formatted_results
            else:
                return "success", formatted_results

        # Fallback
        return "unknown", "알 수 없는 상황입니다."

    def _format_agent_results(
        self,
        agent_results: Optional[Dict[str, AgentResult]]
    ) -> str:
        """
        Format all agent results into a readable string

        Args:
            agent_results: 모든 에이전트 실행 결과 (딕셔너리)
                          병렬 실행된 경우 여러 에이전트의 결과가 포함됨

        Returns:
            Formatted string representation of results
        """
        if not agent_results:
            return "실행된 에이전트가 없습니다."

        formatted_parts = []

        # 성공한 에이전트와 실패한 에이전트를 분리
        successful_agents = {}
        failed_agents = {}

        for agent_name, result in agent_results.items():
            if result.success:
                successful_agents[agent_name] = result
            else:
                failed_agents[agent_name] = result

        # 성공한 에이전트 결과 포맷팅
        if successful_agents:
            for agent_name, result in successful_agents.items():
                formatted_parts.append(f"=== [{agent_name}] 에이전트 결과 ===")
                formatted_parts.append(self._format_single_result(result))
                formatted_parts.append("")  # 빈 줄 추가

        # 실패한 에이전트 결과 포맷팅
        if failed_agents and self.config.config.formatting.include_metadata:
            formatted_parts.append("=== 실패한 에이전트 ===")
            for agent_name, result in failed_agents.items():
                formatted_parts.append(f"\n[{agent_name}]")
                formatted_parts.append(f"오류: {result.error}")

        return "\n".join(formatted_parts)

    def _format_single_result(self, result: AgentResult) -> str:
        """Format a single AgentResult into readable text"""
        if not result.success:
            return f"실행 실패: {result.error}"

        formatted_lines = []

        # Format result field (primary output)
        if result.result:
            formatted_lines.append(f"응답: {result.result}")

        # Format data field (additional info)
        if result.data:
            if isinstance(result.data, dict):
                if 'search_groups' in result.data and self.config.config.formatting.show_sources:
                    groups = result.data['search_groups']
                    if groups:
                        formatted_lines.append(f"검색 그룹: {', '.join(groups)}")

                if 'internal_results_count' in result.data:
                    formatted_lines.append(
                        f"내부 문서 검색 결과: {result.data['internal_results_count']}건"
                    )

                # Format other data fields if metadata is enabled
                if self.config.config.formatting.include_metadata:
                    for key, value in result.data.items():
                        if key not in ['search_groups', 'internal_results_count']:
                            formatted_lines.append(f"{key}: {value}")
            else:
                formatted_lines.append(f"결과: {result.data}")

        # Format metadata if enabled
        if self.config.config.formatting.include_metadata and result.metadata:
            formatted_lines.append(f"메타데이터: {result.metadata}")

        return "\n".join(formatted_lines)

    async def _generate_final_response(
        self, question: str, formatted_context: str, scenario: str
    ) -> str:
        """
        Generate final user-friendly response using LLM with fallback

        Args:
            question: 사용자의 원본 질문
            formatted_context: 포맷팅된 컨텍스트 (에이전트 결과, 에러 메시지 등)
            scenario: 실행 시나리오 ("no_agents", "errors", "success", "partial_success")

        Returns:
            Final response text
        """
        # Use prompts from YAML configuration
        prompts = self.config.prompts

        # Add scenario context to the prompt
        scenario_context = self._get_scenario_context(scenario)
        user_prompt = prompts.user_prompt_template.format(
            question=question,
            agent_result=formatted_context,
            scenario=scenario_context
        )

        override_params = self.get_override_params()

        try:
            # Use request_with_fallback for automatic LLM fallback
            response = await self.request_with_fallback(
                user_prompt=user_prompt,
                system_prompt=prompts.system_prompt,
                **override_params,
            )
            return response
        except Exception as e:
            # Fallback: return formatted context with error notice
            print(f"[WARN {self.name}] All LLMs failed, using fallback response: {e}")
            return self._get_fallback_response(scenario, formatted_context)

    def _get_scenario_context(self, scenario: str) -> str:
        """Get additional context based on scenario from config"""
        scenario_config = self.config.config.scenario_config
        return getattr(scenario_config, scenario, "")

    def _get_fallback_response(self, scenario: str, formatted_context: str) -> str:
        """Get fallback response when LLM is not available from config"""
        fallback_config = self.config.config.fallback_config
        fallback_message = getattr(fallback_config, scenario, "")

        # If fallback message is empty, use formatted_context (for success/partial_success)
        if not fallback_message:
            return formatted_context

        # For errors scenario, append formatted context
        if scenario == "errors" and formatted_context:
            return f"{fallback_message}\n\n{formatted_context}"

        return fallback_message

    def _truncate_response(self, response: str, max_length: int) -> str:
        """Truncate response if it exceeds max length"""
        if len(response) <= max_length:
            return response

        truncated = response[:max_length - 50]  # Leave room for ellipsis message
        return f"{truncated}\n\n... (응답이 너무 길어 일부 생략되었습니다)"
