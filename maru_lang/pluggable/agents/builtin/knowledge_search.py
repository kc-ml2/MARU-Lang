"""
Knowledge Search Agent - Handles company policy, internal documents, and web search
"""
import asyncio
from typing import Dict, Any, Optional, List
from maru_lang.pluggable.agents.base import BaseAgent, AgentResult
from maru_lang.pluggable.retrievers import get_retriever
from maru_lang.core.vector_db.base import RetrieveDocument
from maru_lang.core.vector_db.factory import get_vector_db
from maru_lang.models.vector_db import ChromaDBConfig
from maru_lang.models.agents import WebSearchResult
from maru_lang.services.document import get_all_descendant_group_names
from maru_lang.pluggable.agents.agent_factory import AgentFactory
from maru_lang.configs.manager import get_config_manager


class KnowledgeSearchAgent(BaseAgent):
    """Agent for searching company policies, internal documents, and web sources"""

    def __init__(
        self,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.retriever = None
        self.web_search_enabled = True

        # Preprocessing agents (will be initialized in _setup)
        self.group_classifier = None
        self.intent_extractor = None
        self.keyword_extractor = None

    async def _setup(self) -> None:
        """Initialize knowledge search capabilities"""
        # Initialize VectorDB
        vdb_config = ChromaDBConfig.from_settings()
        vdb = get_vector_db(vdb_config)

        # Initialize Retriever (새로운 Retriever 사용)
        self.retriever = get_retriever(vdb)

        # Load search config (config 구조를 신뢰)
        self.web_search_enabled = self.config.config.search_config.web_search.enabled
        self.search_all_on_empty = self.config.config.search_config.internal_search.search_all_on_empty

        # Initialize preprocessing agents
        config_manager = get_config_manager()
        factory = AgentFactory()

        # Create and initialize group_classifier
        group_classifier_config = config_manager.get_agent('group_classifier')
        if group_classifier_config:
            self.group_classifier = factory.create_agent('group_classifier', group_classifier_config)
            if self.group_classifier:
                await self.group_classifier.initialize()

        # Create and initialize intent_extractor
        intent_extractor_config = config_manager.get_agent('intent_extractor')
        if intent_extractor_config:
            self.intent_extractor = factory.create_agent('intent_extractor', intent_extractor_config)
            if self.intent_extractor:
                await self.intent_extractor.initialize()

        # Create and initialize keyword_extractor
        keyword_extractor_config = config_manager.get_agent('keyword_extractor')
        if keyword_extractor_config:
            self.keyword_extractor = factory.create_agent('keyword_extractor', keyword_extractor_config)
            if self.keyword_extractor:
                await self.keyword_extractor.initialize()

    async def execute(
        self,
        question: str,
        max_internal_results: int = 8,
        max_web_results: int = 5,
        fallback_threshold: float = 0.6,
        metadata: Dict[str, Any] = {},
        **kwargs
    ) -> AgentResult:
        """
        Execute knowledge search combining internal documents and web search

        Args:
            question: Search question
            max_internal_results: Maximum internal search results
            max_web_results: Maximum web search results
            fallback_threshold: Threshold to trigger web search fallback
            **kwargs: Additional parameters

        Returns:
            AgentResult with search results in data field
        """
        try:
            # Step 1: Execute preprocessing agents in parallel
            preprocessing_results = await self._execute_preprocessing_agents(
                question, metadata, **kwargs
            )


            # Step 2: Extract preprocessing results
            preprocessing_info = self._extract_preprocessing_results(
                preprocessing_results, question
            )

            # Step 3: Search internal documents using optimized queries
            internal_results = []

            # Use groups from preprocessing agents
            search_groups = preprocessing_info.get('search_groups', [])

            # Check if forced_groups exists in metadata
            forced_groups = metadata.get('forced_groups', None)

            if not search_groups:
                if forced_groups:
                    # forced_selected_groups가 있으면 그것 사용 (search_all_on_empty 무시)
                    search_groups = forced_groups
                    print(f"⚠️  No groups from group_classifier, using forced_groups: {forced_groups}")
                elif self.search_all_on_empty:
                    # 강제 제한 없고 search_all_on_empty 활성화 시 전체 검색
                    print(f"⚠️  No groups from group_classifier, search_all_on_empty is enabled")
                    search_groups = []

            if self.retriever and (search_groups or (self.search_all_on_empty and not forced_groups)):
                internal_results = await self._search_internal_documents(
                    preprocessing_info.get('search_query', question),
                    search_groups,
                    max_internal_results,
                    preprocessing_info.get('search_keywords', question)
                )

            # Step 4: Determine if web search is needed
            internal_context = self._format_internal_results(internal_results)
            need_web_search = (
                self.web_search_enabled and
                self._should_use_web_search(
                    internal_context, fallback_threshold)
            )

            # Step 5: Perform web search if needed
            web_results = []
            if need_web_search:
                web_results = await self._search_web(
                    preprocessing_info.get('search_query', question), max_web_results
                )

            # Step 6: Generate comprehensive response
            web_context = self._format_web_results(web_results)
            response_text = await self._generate_response(
                question, internal_context, web_context
            )

            # Determine search strategy
            search_strategy = "internal_only"
            if web_results:
                search_strategy = "hybrid" if internal_results else "web_only"

            return AgentResult(
                success=True,
                result=response_text,  # 주요 응답 텍스트
                data={
                    "search_groups": search_groups,
                    "internal_results": internal_results,
                    "web_results": web_results,
                    "preprocessing_info": preprocessing_info,
                    "search_strategy": search_strategy,
                    "internal_results_count": len(internal_results),
                    "web_results_count": len(web_results)
                }
            )

        except Exception as e:
            return AgentResult(
                success=False,
                result="",
                error=f"Knowledge search failed: {str(e)}"
            )

    async def _execute_preprocessing_agents(
        self,
        question: str,
        metadata: Dict[str, Any],
        **kwargs
    ) -> Dict[str, AgentResult]:
        """Execute preprocessing agents in parallel"""
        tasks = []
        agent_names = []

        # Prepare context for agents
        agent_context = {
            "question": question,
            "metadata": metadata,
            **kwargs
        }

        # Create tasks for parallel execution
        if self.group_classifier:
            tasks.append(self.group_classifier.execute(**agent_context))
            agent_names.append('group_classifier')

        if self.intent_extractor:
            tasks.append(self.intent_extractor.execute(**agent_context))
            agent_names.append('intent_extractor')

        if self.keyword_extractor:
            tasks.append(self.keyword_extractor.execute(**agent_context))
            agent_names.append('keyword_extractor')

        # Execute all agents in parallel
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Build result dictionary
            preprocessing_results = {}
            for name, result in zip(agent_names, results):
                if isinstance(result, Exception):
                    print(f"⚠️  Error executing {name}: {result}")
                    preprocessing_results[name] = AgentResult(
                        success=False,
                        result="",
                        error=str(result)
                    )
                else:
                    preprocessing_results[name] = result

            return preprocessing_results

        return {}

    def _extract_preprocessing_results(
        self,
        preprocessing_results: Optional[Dict[str, AgentResult]],
        original_question: str,
    ) -> Dict[str, Any]:
        """Extract and process results from preprocessing agents"""
        if not preprocessing_results:
            return {}

        # Extract group classification results (only from preprocessing)
        search_groups = []
        group_confidence = 0.0
        group_agent_result = preprocessing_results.get('group_classifier')
        if group_agent_result and group_agent_result.success and group_agent_result.data:
            group_data = group_agent_result.data
            search_groups = group_data.get('selected_groups', [])
            group_confidence = group_data.get('confidence', 0.0)

        # Extract intent extraction results
        search_query = original_question
        intent_confidence = 1.0
        intent_agent_result = preprocessing_results.get('intent_extractor')
        if intent_agent_result and intent_agent_result.success and intent_agent_result.data:
            intent_data = intent_agent_result.data
            search_query = intent_data.get('rewritten_question', original_question)
            intent_confidence = intent_data.get('confidence', 1.0)

        # Extract keyword extraction results
        search_keywords = original_question
        keyword_count = 0
        keyword_agent_result = preprocessing_results.get('keyword_extractor')
        if keyword_agent_result and keyword_agent_result.success and keyword_agent_result.data:
            keyword_data = keyword_agent_result.data
            # keyword_extractor returns 'extracted_keywords' as a list
            keywords_list = keyword_data.get('extracted_keywords', [])
            search_keywords = ' '.join(keywords_list) if keywords_list else original_question
            keyword_count = len(keywords_list)

        return {
            "search_groups": search_groups,
            "search_query": search_query,
            "search_keywords": search_keywords,
            "group_confidence": group_confidence,
            "intent_confidence": intent_confidence,
            "keyword_count": keyword_count
        }

    async def _search_internal_documents(
        self,
        question: str,
        document_groups: List[str],
        max_results: int,
        keywords: Optional[str] = None
    ) -> List[RetrieveDocument]:
        """Search internal documents using Retriever"""
        print(f"⚠️  document_groups: {document_groups}")
        # 빈 그룹 리스트 체크
        if not document_groups:
            print("⚠️  No document groups specified, searching all documents")
            if self.search_all_on_empty:
                print("⚠️  No document groups specified, searching all documents")
                # 전체 검색 (document_groups=None)
                try:
                    # 새 Retriever는 동기 메서드 (await 불필요)
                    results = self.retriever.search(
                        query=question,
                        k=max_results,
                        # method="ensemble",  # 기본: ensemble (vector + BM25 + semantic weight)
                        document_groups=None,
                        # embedding_model은 config에서 자동 로드됨
                    )
                    return results
                except Exception as e:
                    print(f"❌ Internal document search failed: {e}")
                    return []
            else:
                print("⚠️  No document groups specified, skipping internal search")
                return []

        # 그룹과 그 자식 그룹들까지 모두 포함 (inclusion 계층 구조 적용)
        all_groups = await get_all_descendant_group_names(document_groups)
        if not all_groups:
            print("⚠️  No valid groups after expansion")
            return []

        try:
            # 새 Retriever로 검색 (ensemble + reranking)
            results = self.retriever.search(
                query=question,
                k=max_results,
                # method="ensemble",  # vector + BM25 + semantic weight 자동 조정
                document_groups=all_groups,
                # use_reranking은 config에서 자동 결정됨
                # embedding_model은 config에서 자동 로드됨
            )
            return results

        except Exception as e:
            print(f"❌ Internal document search failed: {e}")
            return []

    async def _search_web(self, question: str, max_results: int) -> List[WebSearchResult]:
        """Search web sources for additional information"""
        if not self.web_search_enabled:
            return []

        # Implementation for web search
        # This would integrate with web search APIs
        try:
            # Placeholder for web search implementation
            web_results = []
            # Example: web_results.append(WebSearchResult(
            #     title="Example",
            #     url="https://example.com",
            #     content="Example content",
            #     snippet="Example snippet",
            #     relevance_score=0.9
            # ))
            return web_results
        except Exception:
            return []

    def _should_use_web_search(self, internal_context: str, threshold: float) -> bool:
        """Determine if web search should be used based on internal results"""
        if not internal_context.strip():
            return True  # No internal results, use web search

        # Simple heuristic: if internal context is too short, supplement with web
        context_score = min(len(internal_context) / 1000,
                            1.0)  # Normalize to 0-1
        return context_score < threshold

    def _format_internal_results(self, results: List[RetrieveDocument]) -> str:
        """Format internal document search results"""
        if not results:
            return ""

        formatted = []
        for i, doc in enumerate(results, 1):
            content = doc.page_content
            source = doc.source
            score = doc.metadata.get('score', 0.0)
            formatted.append(f"[내부문서 {i}] {source} (유사도: {score:.2f}):\n{content}\n")

        return "\n".join(formatted)

    def _format_web_results(self, results: List[WebSearchResult]) -> str:
        """Format web search results"""
        if not results:
            return ""

        formatted = []
        for i, result in enumerate(results, 1):
            formatted.append(f"[웹검색 {i}] {result.title} ({result.url}):\n{result.content}\n")

        return "\n".join(formatted)

    async def _generate_response(
        self,
        question: str,
        internal_context: str,
        web_context: str
    ) -> str:
        """Generate comprehensive response using LLM with fallback"""
        # Use the prompt template from configuration
        prompts = self.config.prompts
        user_prompt = prompts.user_prompt_template.format(
            question=question,
            internal_context=internal_context or "관련 내부 문서를 찾지 못했습니다.",
            web_context=web_context or "추가 웹 검색 결과가 없습니다."
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
            return f"응답 생성 중 오류가 발생했습니다: {str(e)}"
