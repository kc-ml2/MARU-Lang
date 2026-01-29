"""
Response Agent - Formats and delivers final responses to users
다른 에이전트들의 결과를 받아서 사용자 친화적으로 포맷팅하여 전달하는 에이전트
"""
from typing import Dict, Optional, Union, Literal, overload, AsyncGenerator
from maru_lang.models.agents import AgentSelection, ChatHistory, ExecutionContext
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

    async def execute(
        self,
        context: ExecutionContext
    ) -> AgentResult:

        try:
            response = await self._generate_response(
                context 
            )
            return AgentResult(
                status="success",
                payload={
                    "message": response,
                },
            )

        except Exception as e:
            return AgentResult(
                status="error",
                error=f"Response formatting failed: {str(e)}"
            )

    def _format_agent_results(
        self,
        results: Dict[str, AgentResult],
    ) -> str:
        if not results:
            return "No relevant agents results."

        formatted_parts = []

        for agent_name, result in results.items():
            if result.status == "success" and result.payload:
                message = result.payload.get('message', '') if isinstance(result.payload, dict) else str(result.payload)
                if message:
                    formatted_parts.append(f"=== [{agent_name}] agent result ===")
                    formatted_parts.append(message)
                    formatted_parts.append("")

            elif result.status == "error":
                formatted_parts.append(f"=== [{agent_name}] agent error ===")
                formatted_parts.append(result.error)
                formatted_parts.append("")

        return "\n".join(formatted_parts) if formatted_parts else "No relevant agents results."

    def _determine_scenario(
        self,
        context: ExecutionContext
    ) -> str:
        """
        Determine execution scenario based on context

        Returns:
            scenario: "no_agents", "no_results", "errors", "success", "partial_success", "unknown"
        """
        # Check if agents were selected
        if not context.agent_selection or not context.agent_selection.selected_agents:
            return "no_agents"

        # Check if there are any results
        if not context.agent_results:
            return "no_results"

        # Count successes and errors
        success_count = 0
        error_count = 0

        for result in context.agent_results.values():
            if result.status == "success":
                success_count += 1
            elif result.status == "error":
                error_count += 1

        # Determine scenario based on counts
        if error_count > 0 and success_count == 0:
            return "errors"
        elif success_count > 0 and error_count == 0:
            return "success"
        elif success_count > 0 and error_count > 0:
            return "partial_success"
        else:
            return "unknown"

    @overload
    async def _generate_response(
        self,
        context: ExecutionContext,
        stream: Literal[False] = False
    ) -> str: ...

    @overload
    async def _generate_response(
        self,
        context: ExecutionContext,
        stream: Literal[True] = ...
    ) -> AsyncGenerator[str, None]: ...

    async def _generate_response(
        self,
        context: ExecutionContext,
        stream: bool = False
    ) -> Union[str, AsyncGenerator[str, None]]:
        """
        Generate final user-friendly response using LLM with fallback

        Returns:
            Final response text, or async generator if streaming
        """

        # Use prompts from YAML configuration
        prompts = self.config.prompts
        if not prompts:
            raise ValueError(
                "Response agent requires prompts in configuration")

        scenario = self._determine_scenario(context)
        agent_result_text = self._format_agent_results(context.agent_results)

        if scenario == "no_agents" and context.agent_selection and context.agent_selection.reasoning:
            agent_result_text = context.agent_selection.reasoning

        user_prompt = prompts.user_prompt_template.format(
            question=context.question,
            agent_result=agent_result_text,
            scenario=self._get_scenario_context(scenario)
        )

        override_params = self.get_override_params()

        # Use request_with_fallback for automatic LLM fallback
        response = await self.request_with_fallback(
            user_prompt=user_prompt,
            system_prompt=prompts.system_prompt,
            stream=stream,
            **override_params,
        )
        return response

    def _get_scenario_context(self, scenario: str) -> str:
        """Get additional context based on scenario from config"""
        return getattr(self.scenario_config, scenario, "")
