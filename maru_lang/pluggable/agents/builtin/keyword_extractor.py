"""
Keyword Extractor Agent - Extracts BM25-optimized keywords from questions
"""
from typing import Dict, Any, Optional, List
from maru_lang.pluggable.agents.base import BaseAgent, AgentResult


class KeywordExtractorAgent(BaseAgent):
    """Agent for extracting BM25-optimized keywords from user questions"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.stopwords = set()

    async def _setup(self) -> None:
        """Initialize keyword extraction capabilities"""
        # Load stopwords from config
        # config = self.config.get('extraction_config', {})
        # stopwords_list = config.get('stopwords', [])
        # self.stopwords = set(word.lower() for word in stopwords_list)

    async def execute(
        self,
        question: str,
        max_keywords: int = 7,
        **kwargs
    ) -> AgentResult:
        """
        Execute keyword extraction optimized for BM25 search

        Args:
            question: User question to extract keywords from
            max_keywords: Maximum number of keywords to extract
            **kwargs: Additional parameters

        Returns:
            AgentResult containing extracted keywords
        """
        try:
            # Extract keywords using LLM
            keywords_text = await self._extract_keywords_with_llm(question)

            # Process and validate keywords
            processed_keywords = self._process_keywords(
                keywords_text,
                question,
                max_keywords
            )

            return AgentResult(
                success=True,
                result=' '.join(processed_keywords),  # 주요 출력: 키워드 문자열
                data={
                    'original_question': question,
                    'extracted_keywords': processed_keywords,
                    'bm25_optimized': True
                },
                metadata={
                    'extraction_method': 'llm_based',
                    'preprocessing_applied': True
                }
            )

        except Exception as e:
            return AgentResult(
                success=True,
                result=question,  # 주요 출력: 원본 질문
                data={
                    'original_question': question,
                    'extracted_keywords': [question],
                    'bm25_optimized': False
                },
                metadata={
                    'extraction_method': 'fallback',
                    'preprocessing_applied': False
                }
            )

    async def _extract_keywords_with_llm(
        self,
        question: str,
        **kwargs
    ) -> str:
        """Extract keywords using LLM with fallback"""
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

        # Use request_with_fallback for automatic LLM fallback
        response = await self.request_with_fallback(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            **override_params,
        )
        return response.strip() if response else ""

    def _process_keywords(
        self,
        keywords_text: str,
        original_question: str,
        max_keywords: int
    ) -> List[str]:
        """Process and validate extracted keywords"""
        if not keywords_text.strip():
            return [original_question]

        # Split keywords and clean them
        keywords = []
        for keyword in keywords_text.split():
            keyword = keyword.strip().lower()
            # Remove punctuation and filter out stopwords
            cleaned_keyword = ''.join(
                c for c in keyword if c.isalnum() or c.isspace()).strip()
            if cleaned_keyword and cleaned_keyword not in self.stopwords and len(cleaned_keyword) > 1:
                keywords.append(cleaned_keyword)

        # Remove duplicates while preserving order
        unique_keywords = []
        seen = set()
        for keyword in keywords:
            if keyword not in seen:
                unique_keywords.append(keyword)
                seen.add(keyword)

        return unique_keywords[:max_keywords]
