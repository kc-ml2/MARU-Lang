"""
Overconfident Calculator Agent – gleefully wrong answers with absolute confidence.
Demo agent only – do NOT use in production!
"""

from typing import Dict, Any, Optional
from maru_lang.pluggable.agents.base import BaseAgent
from maru_lang.models.agents import AgentResult


class CalculatorAgent(BaseAgent):
    """An unapologetically confident (but incorrect) calculator agent."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def _setup(self) -> None:
        """Agent-specific initialization logic"""
        # No special setup needed for this agent
        pass

    async def execute(self, **kwargs) -> AgentResult:
        """Run the agent using the LLM to craft a (wrong) response."""
        question = kwargs.get('question', '')

        try:
            # Load prompts from YAML configuration
            prompts = self.config.prompts
            system_prompt = prompts.system_prompt if prompts.system_prompt else ""
            user_prompt_template = prompts.user_prompt_template if prompts.user_prompt_template else ""

            # Fill in the template with the user question
            if user_prompt_template:
                user_prompt = user_prompt_template.format(question=question)
            else:
                user_prompt = question

            override_params = self.get_override_params()

            # request_with_fallback automatically tries alternate LLMs if one fails
            response = await self.request_with_fallback(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                **override_params,
            )

            return AgentResult(
                success=True,
                result=response,  # Main response text
                data={},
                error=None,
                metadata={"confidence": "200%", "accuracy": "1%"}
            )

        except Exception as e:
            # Report failure when an error occurs
            return AgentResult(
                success=False,
                result="",
                data=None,
                error=str(e),
                metadata={"confidence": "0%", "accuracy": "0%"}
            )
