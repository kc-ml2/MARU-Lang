"""
Intent Extractor Agent - Extracts user intent and rewrites queries for search
"""
from typing import Dict, Any, Optional
from maru_lang.pluggable.agents.base import BaseAgent, AgentResult
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
        question: str,
        chat_history: ChatHistory,
        **kwargs
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
            rewritten_query = await self._extract_intent_and_rewrite(
                question,
                chat_history
            )

            return AgentResult(
                success=True,
                result=rewritten_query,  # 주요 출력: 재작성된 질문
                data={
                    'original_question': question,
                    'rewritten_question': rewritten_query,
                    'has_context': True if chat_history.messages else False,
                    'extracted_intent': True,
                },
                metadata={
                    'extraction_method': 'llm_based',
                }
            )

        except Exception as e:
            # Fallback to original question
            return AgentResult(
                success=True,  # Still successful, but using fallback
                result=question,  # 주요 출력: 원본 질문
                data={
                    'original_question': question,
                    'rewritten_question': question,  # Use original as fallback
                    'has_context': True if chat_history.messages else False,
                    'extracted_intent': False,
                },
                metadata={
                    'extraction_method': 'fallback',
                    'error': str(e)
                }
            )

    async def _extract_intent_and_rewrite(
        self,
        question: str,
        chat_history: ChatHistory,
    ) -> str:
        """Extract intent and rewrite query using LLM with fallback"""
        # YAML 설정에서 프롬프트 가져오기
        prompts = self.config.prompts

        # 템플릿에 질문 삽입
        user_prompt = prompts.user_prompt_template.format(
            question=question,
            history_text=chat_history.to_string()
        )

        override_params = self.get_override_params()

        # Use request_with_fallback for automatic LLM fallback
        response = await self.request_with_fallback(
            user_prompt=user_prompt,
            system_prompt=prompts.system_prompt,
            **override_params,
        )

        return response.strip()
