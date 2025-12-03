"""
Chat Pipeline - Clean architecture with dependency injection
채팅 요청을 처리하는 파이프라인
Agent selection -> Execution -> Answer extraction
"""
from typing import AsyncGenerator, List, Optional

from maru_lang.pipelines.base import BasePipeline, PipelineComplete, PipelineMessage
from maru_lang.models.agents import ChatResult, ChatStep, ChatProcess, ExecutionContext, AgentSelection
from maru_lang.pluggable.agents.agent_selector import AgentSelector
from maru_lang.pluggable.agents.agent_executor import AgentExecutor
from maru_lang.models.chat import ChatHistory


class ChatPipeline(BasePipeline):
    """
    Clean architecture chat handler
    Agent selection -> Execution -> Answer extraction
    """

    def __init__(
        self,
        agent_selector: AgentSelector,
        agent_executor: AgentExecutor
    ):
        super().__init__()
        self.agent_selector = agent_selector
        self.agent_executor = agent_executor

    async def process(self):
        """
        Chat pipeline process (큐 기반)

        큐에 ChatProcess를 전달하여 진행 상황 스트리밍
        """
        try:
            # 파라미터는 인스턴스 변수로 저장되어 있어야 함
            question = self._question
            chat_history = self._chat_history
            forced_groups = self._forced_groups

            # Check if LLM servers are available
            from maru_lang.configs.manager import get_config_manager
            config_manager = get_config_manager()
            enabled_llms = config_manager.llm_loader.get_enabled_configs()

            if not enabled_llms:
                # No LLM servers available - return friendly message
                await self.queue.put(PipelineMessage.warning("No enabled LLM servers found"))

                # Skip agent selection and execution
                no_llm_message = (
                    "현재 사용 가능한 LLM 서버가 없습니다.\n\n"
                    "LLM 서버를 등록하거나 활성화한 후 다시 시도해주세요.\n"
                    "설정 방법은 공식 가이드를 참고해주세요."
                )

                await self.queue.put(ChatProcess(
                    step=ChatStep.ANSWER_GENERATION,
                    data=ChatResult(
                        answer=no_llm_message,
                        internal_documents=[],
                    ),
                ))

                await self.queue.put(PipelineComplete())
                return

            # Step 1: Select agents
            selection = await self.agent_selector.select_agents(
                question=question,
                chat_history=chat_history
            )

            await self.queue.put(ChatProcess(
                step=ChatStep.AGENT_SELECTION,
                data=selection,
            ))

            if selection.selected_agents:
                # Step 2: Execute agents
                try:
                    execution_context = ExecutionContext(
                        question=question,
                        progress_queue=self.queue,
                        chat_history=chat_history,
                        metadata={
                            "forced_groups": forced_groups,
                        })

                    execution_result = await self.agent_executor.execute(
                        selection=selection,
                        execution_context=execution_context
                    )
                except Exception as e:
                    await self.queue.put(PipelineMessage.error(f"Error: {e}"))
                await self.queue.put(ChatProcess(
                    step=ChatStep.AGENT_EXECUTION,
                    data=execution_result,
                ))
            else:
                execution_result = None

            # Step 3: Generate final answer using response_agent
            # Response agent handles all scenarios (no agents, errors, success)
            try:
                answer = await self._call_response_agent(
                    question=question,
                    execution_result=execution_result,
                    selection=selection,
                    chat_history=chat_history
                )
            except Exception as e:
                await self.queue.put(PipelineMessage.error(f"Response agent failed: {e}"))
                # Ultimate fallback
                answer = "죄송합니다. 답변을 생성하는 중 오류가 발생했습니다."

            # Convert internal_documents to DocumentReference (without page_content)
            if execution_result:
                internal_documents = []
                for agent_result in execution_result.agent_results.values():
                    if agent_result.data and 'internal_results' in agent_result.data:
                        # internal_results is Dict[str, List[RetrieveDocument]]
                        for doc_list in agent_result.data['internal_results'].values():
                            for doc in doc_list:
                                internal_documents.append(doc.to_document_reference())
            else:
                internal_documents = []


            await self.queue.put(ChatProcess(
                step=ChatStep.ANSWER_GENERATION,
                data=ChatResult(
                    answer=answer,
                    internal_documents=internal_documents
                ),
            ))

            # Final result
            await self.queue.put(PipelineComplete(
                None,
            ))

        except Exception as e:
            await self.queue.put(PipelineMessage.error(f"Pipeline failed: {e}"))
            await self.queue.put(PipelineComplete(data=None))
            raise

    async def process_stream(
        self,
        question: str,
        chat_history: ChatHistory,
        forced_groups: List[str]
    ) -> AsyncGenerator[ChatProcess, None]:
        """
        Process chat request with streaming (legacy compatibility wrapper)

        Yields:
            Step-by-step processing results
        """
        # 파라미터를 인스턴스 변수로 저장
        self._question = question
        self._chat_history = chat_history
        self._forced_groups = forced_groups

        # BasePipeline.run()을 사용
        async for item in self.run():
            # PipelineComplete는 무시 (ChatProcess만 yield)
            if isinstance(item, PipelineComplete):
                continue
            elif isinstance(item, PipelineMessage):
                yield item
                continue
            elif isinstance(item, ChatProcess):
                yield item
                continue

    async def _call_response_agent(
        self,
        question: str,
        execution_result,
        selection,
        chat_history: ChatHistory
    ) -> str:
        """
        Call response_agent to format final response based on execution result
        Response agent is responsible for handling all scenarios:
        - No agents selected (execution_result is None)
        - Agent execution errors
        - Successful agent results

        Args:
            question: 사용자의 원본 질문
            execution_result: 에이전트 실행 결과 (None, errors, agent_results 등 모든 상황 포함)
            selection: AgentSelection result
            chat_history: Chat history

        Returns:
            Formatted final response string
        """
        # Check if response_agent is registered
        response_agent = self.agent_executor.agent_registry.get('response')

        if not response_agent:
            await self.queue.put(PipelineMessage.error("response_agent not found"))
            return "죄송합니다. 응답 생성 에이전트를 찾을 수 없습니다."

        # Initialize response_agent if not already initialized
        if 'response' not in self.agent_executor._initialized_agents:
            try:
                await response_agent.initialize()
                self.agent_executor._initialized_agents.add('response')
            except Exception as e:
                await self.queue.put(PipelineMessage.error(f"Failed to initialize response_agent: {e}"))
                return "죄송합니다. 응답 생성 에이전트 초기화에 실패했습니다."

        # Execute response_agent with execution result
        try:
            result = await response_agent.execute(
                question=question,
                execution_result=execution_result,
                selection=selection,
                chat_history=chat_history
            )

            if result.success and result.result:
                return result.result
            else:
                await self.queue.put(PipelineMessage.error(f"Response agent returned no response: {result.error}"))
                return "죄송합니다. 응답을 생성할 수 없습니다."

        except Exception as e:
            await self.queue.put(PipelineMessage.error(f"Response agent execution failed: {e}"))
            raise

    async def cleanup(self):
        """Clean up resources"""
        await self.agent_executor.cleanup()
