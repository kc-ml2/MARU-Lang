from typing import Optional, List
from maru_lang.configs.manager import get_config_manager
from maru_lang.pipelines.base import BasePipeline, PipelineMessage
from maru_lang.models.agents import ExecutionContext
from maru_lang.pluggable.agents.agent_selector import AgentSelector
from maru_lang.pluggable.agents.agent_executor import AgentExecutor
from maru_lang.models.chat import ChatHistory
from maru_lang.core.relation_db.models.auth import Team
from maru_lang.services.document import get_group_names_by_team_id


class UnExpectedException(Exception):
    pass


class AgentSelectionFailedException(Exception):
    pass


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

    def get_available_agent_names(self) -> List[str]:
        """Get list of available agent names"""
        return self.agent_selector.get_enabled_agents()

    async def process(
        self,
        team: Team,
        question: str,
        chat_history: Optional[ChatHistory] = None,
    ):
        """
        Chat pipeline process (큐 기반)

        큐에 ChatProcess를 전달하여 진행 상황 스트리밍
        """
        try:
            # Check if LLM servers are available
            config_manager = get_config_manager()
            enabled_llms = config_manager.llm_loader.get_enabled_configs()

            if not enabled_llms:
                # No LLM servers available - return friendly message
                raise Exception(
                    "Sorry, no LLM servers are available at the moment. Please try again later."
                )

            # Step 1: Select agents
            selection = await self.agent_selector.select_agents(
                question=question,
                chat_history=chat_history
            )

            if not selection:
                # Agent selection failed
                raise AgentSelectionFailedException("Agent selection failed")

            # Get accessible groups for this team
            accessible_groups = await get_group_names_by_team_id(team.id)

            await self.queue.put(PipelineMessage.info(
                message=selection.reasoning,
                data=selection.to_dict(),
            ))

            if selection.selected_agents:
                # Step 2: Execute agents
                execution_context = ExecutionContext(
                    question=question,
                    progress_queue=self.queue,
                    chat_history=chat_history,
                    metadata={
                        "team_ids": [team.id],  # List to support multi-team search
                        "accessible_groups": accessible_groups,
                    })

                execution_result = await self.agent_executor.execute(
                    selection=selection,
                    execution_context=execution_context
                )
            else:
                execution_result = None

            # Step 3: Generate final answer using response_agent
            # Response agent handles all scenarios (no agents, errors, success)
            try:
                answer = await self.agent_executor.summarize_execution(
                    question=question,
                    execution_result=execution_result,
                    selection=selection,
                    chat_history=chat_history,
                )
            except Exception as e:
                print(e)
                raise UnExpectedException()

            # Convert internal_documents to DocumentReference (without page_content)
            if execution_result:
                internal_documents = []
                for agent_result in execution_result.agent_results.values():
                    if agent_result.data and 'internal_results' in agent_result.data:
                        # internal_results is Dict[str, List[RetrieveDocument]]
                        for doc_list in agent_result.data['internal_results'].values():
                            for doc in doc_list:
                                internal_documents.append(
                                    doc.to_document_reference())
            else:
                internal_documents = []

            await self.queue.put(PipelineMessage.normal(answer, "answer"))

        except AgentSelectionFailedException:
            await self.queue.put(PipelineMessage.error(
                "Sorry, I couldn't find any suitable agents to answer your question at the moment. Please try rephrasing your question or come back later."
            ))
        except UnExpectedException:
            await self.queue.put(PipelineMessage.error("An unexpected error occurred."))
        except Exception as e:
            await self.queue.put(PipelineMessage.warning(str(e)))
        finally:
            await self.queue.put(PipelineMessage.complete())

    async def cleanup(self):
        """Clean up resources"""
        await self.agent_executor.cleanup()
