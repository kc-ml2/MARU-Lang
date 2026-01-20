"""
Response Agent - Formats and delivers final responses to users
다른 에이전트들의 결과를 받아서 사용자 친화적으로 포맷팅하여 전달하는 에이전트
"""
from typing import Optional, Union, Literal, overload, AsyncGenerator
from maru_lang.models.agents import AgentSelection, ExecutionResult, ChatHistory
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
        self.agent_config = self.config.config
        if not self.agent_config:
            raise ValueError(
                "Response agent requires 'config' section in YAML")
        self.formatting_config = self.agent_config.formatting
        if not self.formatting_config:
            raise ValueError(
                "Response agent requires 'config.formatting' in YAML")
        self.scenario_config = self.agent_config.scenario_config
        if not self.scenario_config:
            raise ValueError(
                "Response agent requires 'config.scenario_config' in YAML")
        self.fallback_config = self.agent_config.fallback_config
        if not self.fallback_config:
            raise ValueError(
                "Response agent requires 'config.fallback_config' in YAML")

    async def execute(
        self,
        **kwargs
    ) -> AgentResult:

        question: str = kwargs.get("question", "")
        execution_result: Optional[ExecutionResult] = kwargs.get(
            "execution_result", None)
        selection: Optional[AgentSelection] = kwargs.get("selection", None)
        stream: bool = kwargs.get("stream", True)

        try:
            # Step 1: Determine scenario
            scenario = self._determine_scenario(execution_result, selection)

            # Step 2: Format execution result
            formatted_context = self._format_execution_result(
                execution_result, scenario)

            # Step 3: Generate user-friendly response using LLM based on scenario
            final_response = await self._generate_final_response(
                question, formatted_context, scenario, stream=stream
            )
            return AgentResult(
                success=True,
                result=final_response,
                data={
                    "scenario": scenario,
                    "formatted_context": formatted_context if self.formatting_config.include_metadata else None,  # type: ignore
                }
            )

        except Exception as e:
            return AgentResult(
                success=False,
                result="",
                error=f"Response formatting failed: {str(e)}"
            )

    def _determine_scenario(
        self,
        execution_result: Optional[ExecutionResult],
        selection: Optional[AgentSelection]
    ) -> str:
        """
        Determine execution scenario

        Returns:
            scenario: "no_agents", "errors", "success", "partial_success", "unknown"
        """
        if selection is None:
            return "no_agents"

        if execution_result is None:
            return "unknown"

        has_results = bool(execution_result.agent_results)
        has_errors = bool(execution_result.errors)

        if has_errors and not has_results:
            return "errors"
        elif has_results and has_errors:
            return "partial_success"
        elif has_results:
            return "success"
        else:
            return "unknown"

    def _format_execution_result(
        self,
        execution_result: Optional[ExecutionResult],
        scenario: str
    ) -> str:
        """
        Format execution result based on scenario

        Returns:
            Formatted string with relevant context
        """
        if scenario == "no_agents":
            return "No agents were selected for execution."

        if execution_result is None:
            return "No execution result available."

        formatted_parts = []

        # Format successful agent results
        if execution_result.agent_results:
            for agent_name, result in execution_result.agent_results.items():
                if result.success:
                    formatted_parts.append(
                        f"=== [{agent_name}] agent result ===")
                    formatted_parts.append(self._format_single_result(result))
                    formatted_parts.append("")

        # Format errors (from execution_result.errors)
        if execution_result.errors:
            formatted_parts.append("=== errors ===")
            for agent, error in execution_result.errors.items():
                formatted_parts.append(f"- {agent}: {error}")

        # Format failed agent results (from agent_results with success=False)
        if execution_result.agent_results:
            failed_results = [
                (name, result) for name, result in execution_result.agent_results.items()
                if not result.success
            ]
            if failed_results:
                formatted_parts.append("=== failed agents ===")
                for agent_name, result in failed_results:
                    formatted_parts.append(f"- {agent_name}: {result.error}")

        return "\n".join(formatted_parts) if formatted_parts else "No relevant execution results."

    def _format_single_result(self, result: AgentResult) -> str:
        """Format a single AgentResult into readable text"""
        if not result.success:
            return f"failed: {result.error}"

        formatted_lines = []

        # Format result field (primary output)
        if result.result:
            formatted_lines.append(f"result: {result.result}")

        # Format data field (additional info)
        if result.data:
            if isinstance(result.data, dict):
                if 'internal_results_count' in result.data:
                    formatted_lines.append(
                        f"internal document count: {result.data['internal_results_count']}"
                    )
                if self.formatting_config.show_sources:  # type: ignore
                    if 'search_groups' in result.data:
                        groups = result.data['search_groups']
                        if groups:
                            formatted_lines.append(
                                f"search_groups: {', '.join(groups)}")
                # Format other data fields if metadata is enabled
                if self.formatting_config.include_metadata:  # type: ignore
                    for key, value in result.data.items():
                        if key not in ['search_groups', 'internal_results_count']:
                            formatted_lines.append(f"{key}: {value}")
            else:
                formatted_lines.append(f"result: {result.data}")

        # Format metadata if enabled
        if self.formatting_config.include_metadata and result.metadata:  # type: ignore
            formatted_lines.append(f"metadata: {result.metadata}")

        return "\n".join(formatted_lines)

    @overload
    async def _generate_final_response(
        self,
        question: str,
        formatted_context: str,
        scenario: str,
        stream: Literal[False] = False
    ) -> str: ...

    @overload
    async def _generate_final_response(
        self,
        question: str,
        formatted_context: str,
        scenario: str,
        stream: Literal[True] = ...
    ) -> AsyncGenerator[str, None]: ...

    async def _generate_final_response(
        self,
        question: str,
        formatted_context: str,
        scenario: str,
        stream: bool = False
    ) -> Union[str, AsyncGenerator[str, None]]:
        """
        Generate final user-friendly response using LLM with fallback

        Args:
            question: 사용자의 원본 질문
            formatted_context: 포맷팅된 컨텍스트 (에이전트 결과, 에러 메시지 등)
            scenario: 실행 시나리오 ("no_agents", "errors", "success", "partial_success")
            stream: If True, returns an async generator yielding chunks

        Returns:
            Final response text, or async generator if streaming
        """
        # Use prompts from YAML configuration
        prompts = self.config.prompts
        if not prompts:
            raise ValueError(
                "Response agent requires prompts in configuration")
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
                stream=stream,
                **override_params,
            )
            return response
        except Exception as e:
            # Fallback: return formatted context with error notice
            fallback = self._get_fallback_response(scenario, formatted_context)
            return fallback

    def _get_scenario_context(self, scenario: str) -> str:
        """Get additional context based on scenario from config"""
        return getattr(self.scenario_config, scenario, "")

    def _get_fallback_response(self, scenario: str, formatted_context: str) -> str:
        """Get fallback response when LLM is not available from config"""
        fallback_message = getattr(self.fallback_config, scenario, "")

        # If fallback message is empty, use formatted_context (for success/partial_success)
        if not fallback_message:
            return formatted_context

        # For errors scenario, append formatted context
        if scenario == "errors" and formatted_context:
            return f"{fallback_message}\n\n{formatted_context}"

        return fallback_message
