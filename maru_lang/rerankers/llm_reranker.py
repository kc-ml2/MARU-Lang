"""
LLM-based Reranker Agent

LLM을 사용하여 검색 결과를 재정렬하는 Agent 예시
"""
from typing import List, Tuple
from maru_lang.pluggable.agents.base import BaseAgent, AgentResult
from maru_lang.core.vector_db.base import RetrieveDocument


class LLMRerankerAgent(BaseAgent):
    """
    LLM을 활용한 Reranker Agent

    검색된 문서들을 질의와의 관련성을 LLM이 평가하여 재정렬합니다.
    """

    async def _setup(self) -> None:
        """Initialize the agent"""
        # LLM은 BaseAgent의 get_llm()으로 가져올 수 있음
        pass

    async def execute(
        self,
        query: str,
        documents: List[RetrieveDocument],
        top_k: int = 10,
        **kwargs
    ) -> AgentResult:
        """
        Execute reranking

        Args:
            query: 사용자 질의
            documents: 재정렬할 문서 리스트
            top_k: 반환할 상위 문서 개수

        Returns:
            AgentResult with data=[(idx, score), ...]
        """
        try:
            # LLM 가져오기
            llm = self.get_llm()

            # 문서들을 번호와 함께 포맷팅
            doc_text = ""
            for idx, doc in enumerate(documents):
                # 문서 길이 제한 (비용 절감)
                content = doc.page_content[:500]
                doc_text += f"\n[문서 {idx}]\n{content}\n"

            # Prompt 구성
            prompt = f"""다음 질의와 각 문서의 관련성을 평가하고, 관련성 순으로 정렬하세요.

질의: {query}

문서들:
{doc_text}

각 문서에 대해 관련성 점수(0.0-1.0)를 매기고, 점수가 높은 순서대로 정렬하여 반환하세요.

출력 형식 (JSON):
[
    {{"index": 0, "score": 0.95}},
    {{"index": 2, "score": 0.87}},
    ...
]

상위 {top_k}개만 반환하세요."""

            # LLM 호출
            messages = [{"role": "user", "content": prompt}]
            response = await llm.chat(messages)

            # 응답 파싱 (JSON 추출)
            import json
            import re

            # JSON 블록 찾기
            json_match = re.search(r'\[[\s\S]*\]', response)
            if not json_match:
                return AgentResult(
                    success=False,
                    error="Failed to parse LLM response",
                )

            ranked_docs = json.loads(json_match.group())

            # 결과 변환: [(idx, score), ...]
            result = [(item["index"], item["score"]) for item in ranked_docs[:top_k]]

            return AgentResult(
                success=True,
                data=result,
            )

        except Exception as e:
            return AgentResult(
                success=False,
                error=f"Reranking failed: {str(e)}",
            )
