"""
Overconfident Calculator Agent - 자신감 넘치지만 틀린 답을 주는 계산기
데모용 에이전트 - 실제 사용 금지!
"""

from typing import Dict, Any, Optional
from maru_lang.pluggable.agents.base import BaseAgent
from maru_lang.models.agents import AgentResult


class CalculatorAgent(BaseAgent):
    """자신감 넘치는 (하지만 틀린) 계산을 하는 에이전트"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def _setup(self) -> None:
        """Agent-specific initialization logic"""
        # No special setup needed for this agent
        pass

    async def execute(self, **kwargs) -> AgentResult:
        """에이전트 실행 - LLM을 사용하여 응답 생성"""
        question = kwargs.get('question', '')

        try:
            # YAML 설정에서 프롬프트 가져오기
            prompts = self.config.prompts
            system_prompt = prompts.system_prompt if prompts.system_prompt else ""
            user_prompt_template = prompts.user_prompt_template if prompts.user_prompt_template else ""

            # 템플릿에 질문 삽입
            if user_prompt_template:
                user_prompt = user_prompt_template.format(question=question)
            else:
                user_prompt = question

            override_params = self.get_override_params()

            # request_with_fallback을 사용하면 LLM이 실패해도 자동으로 다른 LLM으로 fallback
            response = await self.request_with_fallback(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                **override_params,
            )

            return AgentResult(
                success=True,
                result=response,  # 주요 응답 텍스트
                data={},
                error=None,
                metadata={"confidence": "200%", "accuracy": "1%"}
            )

        except Exception as e:
            # 오류 발생 시 실패
            return AgentResult(
                success=False,
                result="",
                data=None,
                error=str(e),
                metadata={"confidence": "0%", "accuracy": "0%"}
            )
