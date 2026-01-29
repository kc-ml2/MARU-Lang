from typing import Optional, List
from maru_lang.configs.manager import get_config_manager
from maru_lang.pipelines.base import BasePipeline, PipelineMessage
from maru_lang.models.agents import ExecutionContext
from maru_lang.pluggable.agents.agent_selector import AgentSelector
from maru_lang.pluggable.agents.agent_executor import AgentExecutor
from maru_lang.models.chat import ChatHistory
from maru_lang.core.relation_db.models.auth import Team
from maru_lang.services.document import get_group_names_by_team_id


class NoneAccsessibleDocumentException(Exception):
    pass


class NoneAvailableLLMException(Exception):
    pass


class UnExpectedException(Exception):
    pass


class AgentSelectionFailedException(Exception):
    pass


class AgentExecutionFailedException(Exception):
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
        teams: List[Team],
        question: str,
        chat_history: Optional[ChatHistory] = None,
    ):
        execution_context = None
        try:
            config_manager = get_config_manager()
            enabled_llms = config_manager.llm_loader.get_enabled_configs()
            if not enabled_llms:
                # No LLM servers available - return friendly message
                raise NoneAvailableLLMException()

            # Step 1: Select agents
            selection = await self.agent_selector.select_agents(
                question=question,
                chat_history=chat_history
            )

            if not selection:
                raise AgentSelectionFailedException("Agent selection failed")

            if not selection.selected_agents:
                execution_context = ExecutionContext(
                    question=question,
                    progress_queue=self.queue,
                    agent_selection=selection,
                    team_ids=[team.id for team in teams],
                    team_names=[team.name for team in teams],
                    accessible_groups=[],
                    chat_history=chat_history,
                )
                return

            # Get accessible groups for these teams
            try:
                accessible_groups = []
                for team in teams:
                    groups = await get_group_names_by_team_id(team.id)
                    accessible_groups.extend(groups)
                accessible_groups = list(
                    set(accessible_groups))  # Remove duplicates
            except:
                raise NoneAccsessibleDocumentException()

            await self.queue.put(PipelineMessage.info(
                message=selection.reasoning,
                data=selection.to_dict(),
            ))

            # Step 2: Execute agents
            execution_context = ExecutionContext(
                question=question,
                progress_queue=self.queue,
                agent_selection=selection,
                team_ids=[team.id for team in teams],
                team_names=[team.name for team in teams],
                accessible_groups=accessible_groups,
                chat_history=chat_history,
            )

            await self.agent_executor.execute(execution_context=execution_context)

        except NoneAccsessibleDocumentException:
            # No accessible documents for the team
            # problem with DB or team is disabled
            pass
        except NoneAvailableLLMException as e:
            await self.queue.put(PipelineMessage.error("Sorry, no LLM servers are available at the moment. Please try again later."))
            return
        except AgentSelectionFailedException:
            # system failed to select agents
            await self.queue.put(PipelineMessage.error(
                "Sorry, I couldn't determine which agents to use for your question. Please try rephrasing your question."
            ))
        except AgentExecutionFailedException as e:
            await self.queue.put(PipelineMessage.error(
                f"Sorry, there was an error while processing your request: {str(e)}"
            ))
        except UnExpectedException:
            await self.queue.put(PipelineMessage.error("An unexpected error occurred."))
        except Exception as e:
            await self.queue.put(PipelineMessage.warning(str(e)))
        finally:
            # TODO execution RESULT만 전달하자,?
            # CONTEXT 만으로도 해결할 수 있을까? 그럴듯, Context만 보고 선택하긔
            if execution_context is None:
                return
            summarized_answer = await self.agent_executor.summarize_execution(
                execution_context
            )
            await self.queue.put(PipelineMessage.normal(summarized_answer, "answer"))
            await self.queue.put(PipelineMessage.complete())

    async def cleanup(self):
        """Clean up resources"""
        await self.agent_executor.cleanup()
