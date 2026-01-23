"""
Intent Extractor Agent - Extracts user intent and rewrites queries for search
"""
from typing import Dict, Any, Optional
from maru_lang.pipelines.base import PipelineMessage
from maru_lang.pluggable.agents.base import BaseAgent, AgentResult
from maru_lang.models.agents import ExecutionContext
from maru_lang.models.chat import ChatHistory


class IntentExtractorAgent(BaseAgent):
    """Agent for extracting user intent and rewriting queries for document search"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def _setup(self) -> None:
        """Initialize intent extraction capabilities"""
        pass

    async def execute(
        self,
        context: ExecutionContext,
    ) -> AgentResult:
        """
        Execute intent extraction and query rewriting

        Args:
            question: User's new question/message
            chat_history: Previous conversation context
            max_length: Maximum length of generated question
            **kwargs: Additional parameters

        Returns:
            AgentResult containing extracted intent and rewritten query
        """

        try:
            # Format the prompt with dialogue context
            rewritten_question = await self._extract_intent_and_rewrite(
                context.question,
                context.chat_history
            )

            await context.progress_queue.put(
                PipelineMessage.debug(
                    f"IntentExtractorAgent rewritten question: {rewritten_question}")
            )

            return AgentResult(
                status="success",
                payload={
                    "rewritten_question": rewritten_question
                }
            )

        except Exception as e:
            # Fallback to original question
            return AgentResult(
                status="error",
                error=str(e)
            )

    async def _extract_intent_and_rewrite(
        self,
        question: str,
        chat_history: Optional[ChatHistory],
    ) -> str:
        """Extract intent and rewrite query using LLM with fallback"""
        # YAML 설정에서 프롬프트 가져오기
        prompts = self.config.prompts
        if prompts is None:
            raise ValueError(
                "Prompts configuration is missing in GroupClassifierAgent")

        # 템플릿에 질문 삽입
        user_prompt = prompts.user_prompt_template.format(
            question=question,
            history_text=chat_history.to_string() if chat_history else ""
        )

        override_params = self.get_override_params()

        # Use request_with_fallback for automatic LLM fallback
        response = await self.request_with_fallback(
            user_prompt=user_prompt,
            system_prompt=prompts.system_prompt,
            **override_params,
        )

        return response.strip()
