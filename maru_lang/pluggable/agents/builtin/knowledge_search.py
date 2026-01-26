"""
Knowledge Search Agent - Handles company policy, internal documents"""
import asyncio
import re
from typing import Dict, Any, List, Optional, Union, Tuple
from maru_lang.models.agents import ExecutionContext
from maru_lang.models.chat import ChatHistory
from maru_lang.pipelines.base import PipelineMessage
from maru_lang.pluggable.agents.base import BaseAgent, AgentResult
from maru_lang.pluggable.retrievers import get_retriever
from maru_lang.core.vector_db.base import RetrieveDocument
from maru_lang.pluggable.agents.agent_factory import AgentFactory
from maru_lang.configs.manager import get_config_manager


class KnowledgeSearchAgent(BaseAgent):
    """Agent for searching company policies, internal documents"""

    def __init__(
        self,
        **kwargs,
    ):
        super().__init__(**kwargs)
        config_manager = get_config_manager()
        config_manager.ensure_loaded()  # TODO require?
        factory = AgentFactory()

        # Initialize Retriever (새로운 Retriever 사용)
        self.retriever = get_retriever()
        # Determine whether any groups are configured; if not, disable group classifier
        self.rag_config = config_manager.get_rag_config()
        self.embedder_config = config_manager.get_embedder_config()

        # Create and initialize group_classifier
        group_classifier_cfg = config_manager.get_agent('group_classifier')
        intent_extractor_cfg = config_manager.get_agent('intent_extractor')
        keyword_extractor_cfg = config_manager.get_agent('keyword_extractor')

        if (
            not group_classifier_cfg or
            not intent_extractor_cfg or
            not keyword_extractor_cfg
        ):
            raise ValueError(
                "KnowledgeSearchAgent requires 'group_classifier', "
                "'intent_extractor', and 'keyword_extractor' agents to be configured."
            )

        self.group_classifier = factory.create_agent(
            'group_classifier',
            group_classifier_cfg
        )
        self.intent_extractor = factory.create_agent(
            'intent_extractor',
            intent_extractor_cfg
        )
        self.keyword_extractor = factory.create_agent(
            'keyword_extractor',
            keyword_extractor_cfg
        )

    async def _setup(self) -> None:
        """Initialize knowledge search capabilities"""
        # Initialize VectorDB (system_config.yaml의 vector_db.type에 따라 자동 선택)
        # Initialize preprocessing agents

        await self.group_classifier.initialize()
        await self.intent_extractor.initialize()
        await self.keyword_extractor.initialize()

    def _parse_group_classifier_result(
        self,
        result: AgentResult
    ) -> Tuple[List[str], float, str]:
        """Parse group classifier agent result to extract selected groups"""
        if result.status != "success":
            return [], 0.0, "Group classifier failed"
        if not isinstance(result.payload, dict):
            return [], 0.0, "Invalid payload type"
        selected_groups = result.payload.get('selected_groups', [])
        confidence = result.payload.get('confidence', 0.0)
        reasoning = result.payload.get('reasoning', "")
        return selected_groups, confidence, reasoning

    def _parse_intent_extractor_result(
        self,
        result: AgentResult
    ) -> str:
        """Parse intent extractor agent result to get rewritten query"""
        if result.status != "success":
            return ""
        if not isinstance(result.payload, dict):
            return ""
        rewritten_query = result.payload.get('rewritten_question', "")
        return rewritten_query

    def _parse_keyword_extractor_result(
        self,
        result: AgentResult
    ) -> List[str]:
        """Parse keyword extractor agent result to get extracted keywords"""
        if result.status != "success":
            return []
        if not isinstance(result.payload, dict):
            return []
        extracted_keywords = result.payload.get('extracted_keywords', [])
        return extracted_keywords

    async def _execute_preprocessing_agents(
        self,
        context: ExecutionContext,
    ) -> List[AgentResult]:
        """Execute preprocessing agents in parallel"""
        if (
            not self.group_classifier or
            not self.intent_extractor or
            not self.keyword_extractor
        ):
            raise ValueError(
                "Preprocessing agents are not properly initialized."
            )
        # Create tasks for parallel execution

        tasks = [
            self.group_classifier.execute(context),
            self.intent_extractor.execute(context),
            self.keyword_extractor.execute(context),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Build result dictionary
        preprocessing_results = []
        for result in results:
            if isinstance(result, Exception):
                preprocessing_results.append(AgentResult(
                    status="error",
                    error=str(result)
                ))
            else:
                preprocessing_results.append(result)
        return preprocessing_results

    async def execute(
        self,
        context: ExecutionContext,
    ) -> AgentResult:
        if not context.team_ids:
            return AgentResult(
                status="error",
                error="No team IDs provided - cannot search documents")

        # Step 1: Execute preprocessing agents in parallel

        group_classifier_result, intent_extractor_result, keyword_extractor_result = await self._execute_preprocessing_agents(
            context
        )

        selected_groups, confidence, reasoning = self._parse_group_classifier_result(
            group_classifier_result
        )

        rewritten_question = self._parse_intent_extractor_result(
            intent_extractor_result
        )
        extracted_keywords = self._parse_keyword_extractor_result(
            keyword_extractor_result
        )

        target_groups = selected_groups if selected_groups else context.accessible_groups
        target_query = rewritten_question if rewritten_question else context.question
        target_keywords = extracted_keywords if extracted_keywords else []

        internal_results = await self._search_internal_documents(
            question=target_query,
            search_keywords=target_keywords,
            team_ids=context.team_ids,
            total_retrieval_count=self.rag_config.retriever.default_k,
            retrive_method=self.rag_config.retriever.default_method,
            default_embedding_model=self.embedder_config.default_model
        )

        # # Send pre-reranking results to progress queue
        # pre_rerank_summary = self._format_search_results_summary(
        #     internal_results,
        #     "Search results before reranking"
        # )
        # # await self.log_info(pre_rerank_summary)

        # # rerank internal results
        # if self.retriever.should_rerank():
        #     reranked_results = await self.retriever.rerank_results(
        #         target_query,
        #         internal_results,
        #     )
        #     internal_results = reranked_results

        #     # Send post-reranking results to progress queue
        #     post_rerank_summary = self._format_search_results_summary(
        #         reranked_results,
        #         "Search results after reranking"
        #     )
        #     # await self.log_info(post_rerank_summary)

        internal_context = self._format_internal_results(internal_results)
        internal_results_count = sum(len(docs)
                                     for docs in internal_results.values())

        response = await self._generate_response(
            target_query,
            internal_context,
            context.chat_history,
        )
        return AgentResult(
            status="success",
            payload={
                "message": response,
                "selected_groups": selected_groups,
                "internal_results": internal_results,
                "internal_results_count": internal_results_count,
            },
        )

    async def _search_internal_documents(
        self,
        question: str,
        search_keywords: List[str],
        team_ids: List[int],
        total_retrieval_count: int,
        retrive_method: str,
        default_embedding_model: str,
    ) -> Dict[str, List[RetrieveDocument]]:
        """Search internal documents and policies by team_ids"""
        if not self.retriever:
            return {}

        results = await self.retriever.search(
            query=question,
            top_k=total_retrieval_count,
            embedding_model=default_embedding_model,
            team_ids=team_ids,
            search_method=retrive_method,
        )

        return {"__all__": results}

    def _format_internal_results(
        self,
        results: Dict[str, List[RetrieveDocument]],
    ) -> str:
        """Format internal document search results"""
        if not results:
            return ""

        if len(results) == 1 and '__all__' in results:
            with_all_groups = True
        else:
            with_all_groups = False

        formatted = []
        for group, docs in results.items():
            for i, doc in enumerate(docs, 1):
                content = doc.page_content
                source = doc.source
                score = doc.metadata.get('score', 0.0)
                rerank_score = doc.metadata.get('reranker_score', 0.0)
                if rerank_score:
                    if rerank_score < 0.1:
                        continue
                    # rerank_score 를 score 로 사용
                    score = rerank_score

                if with_all_groups:
                    # group 이 의미 없음. 모든 그룹의 결과를 표시
                    formatted.append(
                        f"[내부 문서 {i}] {source} (유사도: {score:.2f}):\n{content}\n")
                else:
                    formatted.append(
                        f"[{group} 문서 {i}] {source} (유사도: {score:.2f}):\n{content}\n")
        return "\n".join(formatted)

    def _format_search_results_summary(
        self,
        results: Dict[str, List[RetrieveDocument]],
        title: str
    ) -> str:
        """
        Format search results summary for progress queue (id, score only)

        Args:
            results: Dictionary of group -> documents
            title: Title for the summary section

        Returns:
            Formatted string with document IDs and scores
        """
        if not results:
            return f"{title}: No documents found"

        lines = [f"\n📋 {title}"]

        # Check if this is reranked results (check if any doc has reranker_score)
        is_reranked = any(
            doc.metadata.get('reranker_score') is not None
            for docs in results.values()
            for doc in docs
        )

        if is_reranked:
            # For reranked results: merge all groups and display in order
            all_docs = []
            for group, docs in results.items():
                for doc in docs:
                    all_docs.append(doc)

            # Total count
            lines.append(
                f"  Total: {len(all_docs)} documents (merged from all groups)")

            # Display in order
            for i, doc in enumerate(all_docs, 1):
                doc_id = doc.id
                score = doc.metadata.get('score', 0.0)
                doc_name = doc.metadata.get('document_name', 'unknown')
                reranker_score = doc.metadata.get('reranker_score')

                lines.append(
                    f"    {i}. {doc_name} (id: {doc_id[:8]}..., rerank: {reranker_score:.3f})")
        else:
            # For non-reranked results: display by group
            for group, docs in results.items():
                if docs:
                    display_group_name = group if group != '__all__' else 'All groups'
                    lines.append(
                        f"  {display_group_name} - {len(docs)} documents")
                    for i, doc in enumerate(docs, 1):
                        doc_id = doc.id
                        score = doc.metadata.get('score', 0.0)
                        doc_name = doc.metadata.get('document_name', 'unknown')
                        rrf_score = doc.metadata.get('rrf_score')

                        if rrf_score is not None:
                            lines.append(
                                f"    {i}. {doc_name} (id: {doc_id[:8]}..., rrf: {rrf_score:.3f})")
                        else:
                            lines.append(
                                f"    {i}. {doc_name} (id: {doc_id[:8]}..., score: {score:.3f})")

        return "\n".join(lines)

    async def _generate_response(
        self,
        question: str,
        internal_context: str,
        chat_history: Optional[ChatHistory] = None,
    ) -> str:
        """Generate comprehensive response using LLM with fallback"""
        # Use the prompt template from configuration
        prompts = self.config.prompts
        if prompts is None:
            raise ValueError(
                "Prompts configuration is missing in GroupClassifierAgent")

        user_prompt = prompts.user_prompt_template.format(
            question=question,
            internal_context=internal_context or "관련 내부 문서를 찾지 못했습니다.",
            chat_history=chat_history.to_string(
                only_user_content=True) if chat_history else "",
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
            print(f"❌ 응답 생성 중 오류가 발생했습니다: {e}")
            return f"응답 생성 중 오류가 발생했습니다: {str(e)}"
