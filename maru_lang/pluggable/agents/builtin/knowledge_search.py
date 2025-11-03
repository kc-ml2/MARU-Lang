"""
Knowledge Search Agent - Handles company policy, internal documents"""
import asyncio
from typing import Dict, Any, List, Optional, Union
from maru_lang.models.chat import ChatHistory
from maru_lang.pipelines.base import PipelineMessage
from maru_lang.pluggable.agents.base import BaseAgent, AgentResult
from maru_lang.pluggable.retrievers import RetriveMethod, get_retriever
from maru_lang.core.vector_db.base import RetrieveDocument
from maru_lang.core.vector_db.factory import get_vector_db
from maru_lang.pluggable.agents.agent_factory import AgentFactory
from maru_lang.configs.manager import get_config_manager


class KnowledgeSearchAgent(BaseAgent):
    """Agent for searching company policies, internal documents"""

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


    async def _setup(self) -> None:
        """Initialize knowledge search capabilities"""
        # Initialize VectorDB (system_config.yaml의 vector_db.type에 따라 자동 선택)
        # Initialize preprocessing agents
        config_manager = get_config_manager()
        config_manager.ensure_loaded()

        vdb = get_vector_db()
        factory = AgentFactory()

        # Initialize Retriever (새로운 Retriever 사용)
        self.retriever = get_retriever(vdb)
        # Determine whether any groups are configured; if not, disable group classifier
        self.rag_config = config_manager.get_rag_config()
    
        # Create and initialize group_classifier
        group_classifier_config = config_manager.get_agent('group_classifier')
        self.group_classifier = factory.create_agent('group_classifier', group_classifier_config)
        if self.group_classifier:
            await self.group_classifier.initialize()

        # Create and initialize intent_extractor
        intent_extractor_config = config_manager.get_agent('intent_extractor')
        self.intent_extractor = factory.create_agent('intent_extractor', intent_extractor_config)
        if self.intent_extractor:
            await self.intent_extractor.initialize()

        # Create and initialize keyword_extractor
        keyword_extractor_config = config_manager.get_agent('keyword_extractor')
        self.keyword_extractor = factory.create_agent('keyword_extractor', keyword_extractor_config)
        if self.keyword_extractor:
            await self.keyword_extractor.initialize()

    async def execute(
        self,
        question: str,
        metadata: Dict[str, Any] = {},
        progress_queue: Optional[asyncio.Queue] = None,
        **kwargs
    ) -> AgentResult:
        # Set progress queue if provided (in case not set by executor)
        if progress_queue:
            self.set_progress_queue(progress_queue)
        """
        Execute knowledge search combining internal documents

        Args:
            question: Search question
            **kwargs: Additional parameters

        Returns:
            AgentResult with search results in data field
        """


        try:
            # Check if forced_groups exists in metadata
            forced_groups = metadata.get('forced_groups', {})

            # forced_groups가 없으면 검색할 수 없으므로 바로 리턴
            if not forced_groups:
                await self.log_warning("No accessible document groups - skipping knowledge search")
                return AgentResult(
                    success=True,
                    result="No document groups available for search.",
                    metadata={}
                )

            retrive_method = self.rag_config.retriever.default_method
            forced_groups_message = f"Selected groups from metadata: {forced_groups}"
            await self.log_info(forced_groups_message)
            await self.log_info(f"Retrieve method: {retrive_method}")
            # Step 1: Execute preprocessing agents in parallel
            preprocessing_results = await self._execute_preprocessing_agents(
                question, 
                metadata,
                progress_queue,
                **kwargs
            )

            group_agent_result = preprocessing_results.get('group_classifier', None)
            default_embedding_model = group_agent_result.data.get('default_embedding_model') if group_agent_result else None

            # Fallback to config if default_embedding_model is None
            if not default_embedding_model:
                config_manager = get_config_manager()
                embedder_config = config_manager.get_embedder_config()
                if embedder_config and embedder_config.default_model:
                    default_embedding_model = embedder_config.default_model
                    await self.log_warning(f"No default_embedding_model from classifier, using config: {default_embedding_model}")
                else:
                    raise ValueError(
                        "No embedding model available. Please configure default_model in embedder_config.yaml"
                    )

            if group_agent_result and group_agent_result.success:
                # 그룹 분류 결과 사용
                selected_groups = group_agent_result.data.get('selected_groups')
                total_retrieval_count = group_agent_result.data.get('total_retrieval_count')
            else:
                selected_groups = {}
                # Use default_k from RAG config instead of 0
                total_retrieval_count = self.rag_config.retriever.default_k
                await self.log_warning(f"Selected groups: None, using default_k={total_retrieval_count}")

            
            intent_agent_result = preprocessing_results.get('intent_extractor', None)

            if intent_agent_result and intent_agent_result.success:
                search_query = intent_agent_result.data.get('rewritten_question')
                await self.log_info(f"Rewritten query: {search_query}")
            else:
                search_query = question
                await self.log_warning("No intent extraction result, using original question")

            keyword_agent_result = preprocessing_results.get('keyword_extractor', None)
            if keyword_agent_result and keyword_agent_result.success:
                search_keywords = keyword_agent_result.data.get('extracted_keywords')
                await self.log_info(f"Extracted keywords: {search_keywords}")
            else:
                search_keywords = []
                await self.log_warning("No keywords extracted, fallback to vector-only search")
                # 오류 나면 vector 로만
                retrive_method = "vector"


            if not selected_groups:
                # forced_groups가 있으면 그것 사용
                if forced_groups:
                    selected_groups = {
                        group: {
                            'embedding_model': default_embedding_model,
                            'retrieval_count': total_retrieval_count
                        }
                        for group in forced_groups
                    }

            # forced_groups 기반으로만 검색 (selected_groups가 없으면 검색 안함)
            if selected_groups:
                internal_results = await self._search_internal_documents(
                    search_query,
                    search_keywords,
                    selected_groups,
                    total_retrieval_count,
                    retrive_method,
                    default_embedding_model,
                )

                # Send pre-reranking results to progress queue
                pre_rerank_summary = self._format_search_results_summary(
                    internal_results,
                    "Search results before reranking"
                )
                await self.log_info(pre_rerank_summary)

                # rerank internal results
                if self.retriever.should_rerank():
                    reranked_results = await self.retriever.rerank_results(
                        question,
                        internal_results,
                    )
                    internal_results = reranked_results

                    # Send post-reranking results to progress queue
                    post_rerank_summary = self._format_search_results_summary(
                        reranked_results,
                        "Search results after reranking"
                    )
                    await self.log_info(post_rerank_summary)
            else:
                internal_results = {}
                await self.log_warning("No accessible document groups - skipping knowledge search")

            internal_context = self._format_internal_results(internal_results)
            internal_results_count = sum(len(docs) for docs in internal_results.values())

            response_text = await self._generate_response(
                question,
                internal_context,
                kwargs.get('chat_history', None)
            )

            return AgentResult(
                success=True,
                result=response_text,  # 주요 응답 텍스트
                data={
                    "selected_groups": selected_groups,
                    "internal_results": internal_results,
                    "internal_results_count": internal_results_count,
                }
            )

        except Exception as e:
            error_msg = f"Knowledge search failed: {str(e)}"
            return AgentResult(
                success=False,
                result="",
                error=error_msg
            )

    async def _execute_preprocessing_agents(
        self,
        question: str,
        metadata: Dict[str, Any],
        progress_queue: Optional[asyncio.Queue] = None,
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
            tasks.append(self.group_classifier.execute(
                progress_queue=progress_queue,
                **agent_context))
            agent_names.append('group_classifier')

        if self.intent_extractor:
            tasks.append(self.intent_extractor.execute(
                progress_queue=progress_queue,
                **agent_context))
            agent_names.append('intent_extractor')

        if self.keyword_extractor:
            tasks.append(self.keyword_extractor.execute(
                progress_queue=progress_queue,
                **agent_context))
            agent_names.append('keyword_extractor')

        # Execute all agents in parallel
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            try:
                # Build result dictionary
                preprocessing_results = {}
                for name, result in zip(agent_names, results):
                    if isinstance(result, Exception):
                        await self.log_error(f"Error executing {name}: {result}")
                        preprocessing_results[name] = AgentResult(
                            success=False,
                            result="",
                            error=str(result)
                        )
                    else:
                        preprocessing_results[name] = result
            except Exception as e:
                await self.log_error(f"Error executing preprocessing agents: {e}")
                return {}
            return preprocessing_results

        return {}

    async def _search_internal_documents(
        self,
        question: str,
        search_keywords: List[str],
        selected_groups: Dict[str, Union[str, int]],
        total_retrieval_count: int,
        retrive_method: RetriveMethod,
        default_embedding_model: str,
    ) -> Dict[str, List[RetrieveDocument]]:
        """Search internal documents and policies"""
        if not self.retriever:
            return {}
        # No groups specified
        if not selected_groups:
            await self.log_info(f"Searching all groups total {total_retrieval_count} documents with {default_embedding_model}")
            result = await self.retriever.search(
                query=question,
                top_k=total_retrieval_count,
                embedding_model=default_embedding_model,
                keywords=search_keywords,
                retrive_method=retrive_method,
            )
            return {"__all__": result}
        else:
            await self.log_info(f"Searching {list(selected_groups.keys())} groups total {total_retrieval_count} documents")

        results = {}
        for group, selected_group in selected_groups.items():
            embedding_model = selected_group.get('embedding_model')
            top_k = selected_group.get('retrieval_count')

            # Fallback to default if embedding_model is None
            if not embedding_model:
                embedding_model = default_embedding_model
                await self.log_warning(f"No embedding model for group '{group}', using default: {embedding_model}")

            await self.log_info(f"Searching group '{group}' with top_k={top_k} with {embedding_model}")

            group_results = await self.retriever.search(
                query=question,
                top_k=top_k,
                embedding_model=embedding_model,
                keywords=search_keywords,
                document_groups=[group],
                retrive_method=retrive_method,
            )
            results[group] = group_results

        return results

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
            lines.append(f"  Total: {len(all_docs)} documents (merged from all groups)")

            # Display in order
            for i, doc in enumerate(all_docs, 1):
                doc_id = doc.id
                score = doc.metadata.get('score', 0.0)
                doc_name = doc.metadata.get('document_name', 'unknown')
                reranker_score = doc.metadata.get('reranker_score')

                lines.append(f"    {i}. {doc_name} (id: {doc_id[:8]}..., rerank: {reranker_score:.3f})")
        else:
            # For non-reranked results: display by group
            for group, docs in results.items():
                if docs:
                    display_group_name = group if group != '__all__' else 'All groups'
                    lines.append(f"  {display_group_name} - {len(docs)} documents")
                    for i, doc in enumerate(docs, 1):
                        doc_id = doc.id
                        score = doc.metadata.get('score', 0.0)
                        doc_name = doc.metadata.get('document_name', 'unknown')
                        rrf_score = doc.metadata.get('rrf_score')

                        if rrf_score is not None:
                            lines.append(f"    {i}. {doc_name} (id: {doc_id[:8]}..., rrf: {rrf_score:.3f})")
                        else:
                            lines.append(f"    {i}. {doc_name} (id: {doc_id[:8]}..., score: {score:.3f})")

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
        user_prompt = prompts.user_prompt_template.format(
            question=question,
            internal_context=internal_context or "관련 내부 문서를 찾지 못했습니다.",
            chat_history=chat_history.to_string(only_user_content=True) if chat_history else "",
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
