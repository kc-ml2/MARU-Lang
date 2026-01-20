"""
Agent Executor/Orchestrator - Manages agent execution
"""
import asyncio
from typing import Dict, Any, List, Optional, Union, AsyncGenerator
from maru_lang.models.chat import ChatHistory
from maru_lang.pluggable.agents.base import BaseAgent
from maru_lang.models.agents import AgentResult, AgentSelection, ExecutionResult, ExecutionContext
from maru_lang.pluggable.agents.agent_factory import AgentFactory
from maru_lang.pipelines.base import PipelineMessage


class AgentExecutor:
    """
    Orchestrates the execution of selected agents
    Manages parallel/sequential execution, dependencies, and error handling
    """

    def __init__(self):
        self.agent_registry: Dict[str, BaseAgent] = {}
        self._initialized_agents: set = set()

    def register_agent(self, agent: BaseAgent) -> None:
        """
        Register an agent in the executor

        Args:
            agent: Agent instance to register
        """
        self.agent_registry[agent.name] = agent

    def register_agents(self, agents: List[BaseAgent]) -> None:
        """
        Register multiple agents

        Args:
            agents: List of agent instances
        """
        for agent in agents:
            self.register_agent(agent)

    async def execute(
        self,
        selection: AgentSelection,
        execution_context: ExecutionContext
    ) -> Optional[ExecutionResult]:
        """
        Execute selected agents according to strategy

        Args:
            selection: Agent selection result
            execution_context: Context data for agents (question, user, etc.)
            strategy: Execution strategy ("sequential", "parallel", "conditional")

        Returns:
            ExecutionResult with all agent outputs
        """
        errors = {}

        # Initialize all selected agents
        for agent_name in selection.selected_agents:
            if agent_name not in self.agent_registry:
                error_msg = f"Agent '{agent_name}' not registered (available: {', '.join(list(self.agent_registry.keys()))})"
                errors[agent_name] = error_msg
                continue

            success, message = await self._initialize_agent(agent_name)

            if not success:
                errors[agent_name] = message or f"Failed to initialize agent: {agent_name}"
                continue

        if errors:
            return ExecutionResult(
                agent_results={},
                execution_order=[],
                success=False,
                errors=errors
            )
        # # Prepare agent-specific parameters from selection
        # agent_params = selection.parameters or {}

        # # Use execution_order if provided, otherwise fall back to selected_agents
        # execution_order = selection.execution_order if selection.execution_order else selection.selected_agents

        # Execute agents sequentially
        try:
            agent_results, executed_order = await self._execute_sequential(
                execution_context,
                selection,
            )
            return ExecutionResult(
                agent_results=agent_results,
                execution_order=executed_order,
                success=True,
            )
        except Exception as e:
            error_msg = f"Execution failed: {str(e)}"
            await execution_context.progress_queue.put(
                PipelineMessage.error(error_msg)
            )
            return None

    async def summarize_execution(
        self,
        question: str,
        selection: Optional[AgentSelection] = None,
        execution_result: Optional[ExecutionResult] = None,
        chat_history: Optional[ChatHistory] = None
    ) -> Union[str, AsyncGenerator[str, None]]:
        """
        Call response_agent to generate final response

        Args:
            question: User's question
            selection: Agent selection result
            execution_result: Agent execution result
            chat_history: Chat history

        Returns:
            Response string or async generator for streaming
        """
        response_agent = self.agent_registry.get('response')

        if not response_agent:
            return "Sorry, the response generation agent is not available."

        success, error = await self._initialize_agent('response')
        if not success:
            return f"Failed to initialize response agent: {error}"

        response = await response_agent.execute(
            question=question,
            execution_result=execution_result,
            selection=selection,
            chat_history=chat_history
        )

        if response.success and response.result:
            return response.result
        return "Sorry, unable to generate a response."

    async def _initialize_agent(
        self,
        agent_name: str,
    ) -> tuple[bool, Optional[str]]:
        """
        Initialize an agent if not already initialized

        Args:
            agent_name: Name of the agent to initialize
            progress_queue: Optional queue for progress messages

        Returns:
            Tuple of (success, error_message)
        """
        if agent_name not in self.agent_registry:
            return False, f"Agent '{agent_name}' not found in registry"

        if agent_name not in self._initialized_agents:
            try:
                agent = self.agent_registry[agent_name]
                await agent.initialize()
                self._initialized_agents.add(agent_name)
                return True, None
            except Exception as e:
                error_msg = f"Failed to initialize agent '{agent_name}': {str(e)}"
                return False, error_msg

        return True, None

    async def _execute_sequential(
        self,
        context: ExecutionContext,
        selection: AgentSelection,
    ) -> tuple[Dict[str, AgentResult], List[str]]:
        """
        Execute agents sequentially, chaining results as input to next agent.
        Stops execution if any agent fails.
        """
        results = {}
        executed = []
        parameters = selection.parameters or {}
        # Save original question before any modification
        if "original_question" not in context.metadata:
            context.metadata["original_question"] = context.question

        for agent_name in selection.execution_order:
            agent = self.agent_registry.get(agent_name)
            if not agent:
                raise Exception(f"Agent '{agent_name}' not found in registry")

            await context.progress_queue.put(
                PipelineMessage.debug(
                    f"Executing agent '{agent_name}'..."))

            # Merge context with agent-specific params
            agent_context = context.to_dict()

            agent_context.update(parameters.get(agent_name, {}))

            # Execute agent
            result = await agent.execute(**agent_context)

            results[agent_name] = result
            executed.append(agent_name)

            # If agent failed, stop execution chain
            if not result.success:
                raise Exception(
                    f"Agent '{agent_name}' execution failed: {result.error}")

            # Chain result to next agent: update question with current result
            if result.result:
                next_input = ""
                if isinstance(result.result, str):
                    next_input = result.result
                else:
                    async for chunk in result.result:
                        next_input += chunk

                context.question = next_input  # Next agent receives this as input
                # Also store in metadata for reference
                context.metadata[f"{agent_name}_result"] = next_input
                if result.data:
                    context.metadata[f"{agent_name}_data"] = result.data
        return results, executed

    def get_agent_capabilities(self) -> Dict[str, Dict[str, Any]]:
        """Get capabilities of all registered agents"""
        return {
            name: agent.get_capabilities()
            for name, agent in self.agent_registry.items()
        }

    async def cleanup(self) -> None:
        """Clean up all registered agents"""
        for agent_name in self._initialized_agents:
            if agent_name in self.agent_registry:
                try:
                    await self.agent_registry[agent_name].cleanup()
                except Exception as e:
                    print(f"Error cleaning up agent {agent_name}: {e}")

        self._initialized_agents.clear()
