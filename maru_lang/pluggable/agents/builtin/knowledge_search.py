"""
Knowledge Search Agent - Handles company policy, internal documents, and web search
"""
import asyncio
from typing import Dict, Any, Optional, List
from maru_lang.pluggable.agents.base import BaseAgent, AgentResult
from maru_lang.pluggable.retrievers import get_retriever
from maru_lang.core.vector_db.base import RetrieveDocument
from maru_lang.core.vector_db.factory import get_vector_db
from maru_lang.models.agents import WebSearchResult
from maru_lang.pluggable.agents.agent_factory import AgentFactory
from maru_lang.configs.manager import get_config_manager
from maru_lang.services.document import get_all_descendant_group_names


class KnowledgeSearchAgent(BaseAgent):
    """Agent for searching company policies, internal documents, and web sources"""

    def __init__(
        self,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.retriever = None        
        # Preprocessing agents (will be initialized in _setup)
        self.group_classifier = None
        self.intent_extractor = None
        self.keyword_extractor = None
        self.groups_configured = True

    async def _setup(self) -> None:
        """Initialize knowledge search capabilities"""
        # Initialize VectorDB (system_config.yaml의 vector_db.type에 따라 자동 선택)
        vdb = get_vector_db()

        # Initialize Retriever (새로운 Retriever 사용)
        self.retriever = get_retriever(vdb)

        # Load search config (config 구조를 신뢰)
        self.web_search_enabled = self.config.config.search_config.web_search.enabled
        self.search_all_on_empty = self.config.config.search_config.internal_search.search_all_on_empty

        # Initialize preprocessing agents
        config_manager = get_config_manager()
        config_manager.ensure_loaded()
        factory = AgentFactory()

        # Determine whether any groups are configured; if not, disable group classifier
        rag_loader = getattr(config_manager, "rag_loader", None)
        if rag_loader is not None:
            if not getattr(rag_loader, "all_groups", None):
                rag_loader.reload()
            self.groups_configured = bool(getattr(rag_loader, "all_groups", {}))
        else:
            self.groups_configured = False

        # Create and initialize group_classifier
        group_classifier_config = config_manager.get_agent('group_classifier')
        if self.groups_configured and group_classifier_config:
            self.group_classifier = factory.create_agent('group_classifier', group_classifier_config)
            if self.group_classifier:
                await self.group_classifier.initialize()
        elif not self.groups_configured:
            print("⚠️  No groups defined in RAG config; group_classifier will be skipped")

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
        metadata: Dict[str, Any] = {},
        **kwargs
    ) -> AgentResult:
        """
        Execute knowledge search combining internal documents and web search

        Args:
            question: Search question
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
            internal_results = {}

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
                    print("⚠️  No groups from group_classifier, search_all_on_empty is enabled")
                    search_groups = []


            if self.retriever and (search_groups or (self.search_all_on_empty and not forced_groups)):
                group_weights = preprocessing_info.get('group_weights', {})
                internal_results = await self._search_internal_documents(
                    preprocessing_info.get('search_query', question),
                    search_groups,
                    group_weights,
                )

            # Step 4: Determine if web search is needed
            internal_context = self._format_internal_results(internal_results)

            response_text = await self._generate_response(
                question, internal_context
            )
            internal_results_count = sum(len(docs) for docs in internal_results.values())
            # Determine search strategy
            search_strategy = "internal_only"
            print(f"search_strategy: {search_strategy}")
            return AgentResult(
                success=True,
                result=response_text,  # 주요 응답 텍스트
                data={
                    "search_groups": search_groups,
                    "internal_results": internal_results,
                    "preprocessing_info": preprocessing_info,
                    "search_strategy": search_strategy,
                    "internal_results_count": internal_results_count,
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
        group_confidences = {}
        group_weights = {}
        group_agent_result = preprocessing_results.get('group_classifier')
        if group_agent_result and group_agent_result.success and group_agent_result.data:
            group_data = group_agent_result.data
            search_groups = group_data.get('selected_groups', [])
            group_confidence = group_data.get('confidence', 0.0)
            group_confidences = group_data.get('group_confidences', {})

            # Convert group confidences to weights aligned with selected_groups
            if search_groups:
                selected_confidences = [group_confidences.get(group, 0.0) for group in search_groups]
                total_selected_confidence = sum(selected_confidences)

                if total_selected_confidence > 0:
                    group_weights = {
                        group: confidence / total_selected_confidence
                        for group, confidence in zip(search_groups, selected_confidences)
                    }
                else:
                    # 모든 선택된 그룹의 confidence가 0이면 그룹 선택이 없는 것으로 판단
                    print("⚠️  Group confidences sum to 0; treating as no group selection")
                    search_groups = []
                    group_weights = {}
            elif group_confidences:
                total_confidence = sum(group_confidences.values())
                if total_confidence > 0:
                    group_weights = {
                        group: confidence / total_confidence
                        for group, confidence in group_confidences.items()
                    }

            print(
                f"[GroupClassifier] groups={search_groups}, confidence={group_confidence}, "
                f"group_confidences={group_confidences}, group_weights={group_weights}"
            )
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
            "group_confidences": group_confidences,
            "group_weights": group_weights,
            "intent_confidence": intent_confidence,
            "keyword_count": keyword_count
        }

    async def _search_internal_documents(
        self,
        question: str,
        document_groups: List[str],
        group_weights: Dict[str, float],
    ) -> Dict[str, List[RetrieveDocument]]:
        """Search internal documents and policies"""
        if not self.retriever:
            print("⚠️  Retriever is not initialized; skipping internal search")
            return {}

        # No groups specified
        if not document_groups:
            if self.search_all_on_empty:
                print("⚠️  No document groups specified, searching all documents")
                try:
                    print("[DEBUG] Running full search with no document_groups")
                    return await self.retriever.search(
                        query=question,
                    )
                except Exception as e:
                    print(f"❌ Internal document search failed: {e}")
                    return {}
            else:
                print("⚠️  No document groups specified, skipping internal search")
                return {}

        try:
            # 각 그룹과 그 descendants를 매핑
            flat_document_groups = {}
            for group in document_groups:
                descendants = await get_all_descendant_group_names([group])
                flat_document_groups[group] = descendants or [group]

            return await self.retriever.search(
                query=question,
                document_group_map=flat_document_groups,
                document_group_weights=group_weights,
            )
        except Exception as e:
            print(f"❌ Internal document search failed: {e}")
            return {}

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
                if with_all_groups:
                    # group 이 의미 없음. 모든 그룹의 결과를 표시
                    formatted.append(f"[내부 문서 {i}] {source} (유사도: {score:.2f}):\n{content}\n")
                else:
                    formatted.append(f"[{group} 문서 {i}] {source} (유사도: {score:.2f}):\n{content}\n")
        return "\n".join(formatted)

    async def _generate_response(
        self,
        question: str,
        internal_context: str,
    ) -> str:
        """Generate comprehensive response using LLM with fallback"""
        # Use the prompt template from configuration
        prompts = self.config.prompts
        user_prompt = prompts.user_prompt_template.format(
            question=question,
            internal_context=internal_context or "관련 내부 문서를 찾지 못했습니다.",
            web_context=""
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
