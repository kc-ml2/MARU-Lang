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
        execution_context: ExecutionContext
    ) -> None:
        errors = {}
        # Initialize all selected agents
        for agent_name in execution_context.agent_selection.selected_agents:
            if agent_name not in self.agent_registry:
                error_msg = f"Agent '{agent_name}' not registered (available: {', '.join(list(self.agent_registry.keys()))})"
                errors[agent_name] = error_msg
                continue

            success, message = await self._initialize_agent(agent_name)

            if not success:
                errors[agent_name] = message or f"Failed to initialize agent: {agent_name}"
                continue

        if errors:
            raise Exception(
                f"Failed to initialize agents: {errors}"
            )

        # Execute agents sequentially
        await self._execute_sequential(execution_context)

    async def _execute_sequential(
        self,
        context: ExecutionContext,
    ) -> None:
        """
        Execute agents sequentially, chaining results as input to next agent.
        Stops execution if any agent fails.
        """

        for agent_name in context.agent_selection.execution_order:
            agent = self.agent_registry.get(agent_name)
            if not agent:
                raise Exception(f"Agent '{agent_name}' not found in registry")

            await context.progress_queue.put(
                PipelineMessage.debug(
                    f"Executing agent '{agent_name}'..."))

            # Execute agent
            result = await agent.execute(context)

            # TODO dettach
            # 만약 stream이면 다음 agent를 실행하기전에 결과를 받아오도록 하자,
            if isinstance(result.payload, AsyncGenerator):
                # Collect stream result
                stream_output = ""
                await context.progress_queue.put(
                    PipelineMessage.info(
                        f"Agent '{agent_name}' streaming output...")
                )
                async for chunk in result.payload:
                    stream_output += chunk
                    await context.progress_queue.put(
                        PipelineMessage.info(chunk))
                result.payload = stream_output
                await context.progress_queue.put(
                    PipelineMessage.info(
                        f"Agent '{agent_name}' completed streaming."))
            elif isinstance(result.payload, str):
                await context.progress_queue.put(
                    PipelineMessage.info(
                        f"Agent '{agent_name}' completed with result: {result.payload[:100]}..."))
            else:
                await context.progress_queue.put(
                    PipelineMessage.info(
                        f"Agent '{agent_name}' completed with non-string result."))

            if result.status == "error":
                await context.progress_queue.put(
                    PipelineMessage.error(
                        f"Agent '{agent_name}' execution failed: {result.error}"))

            context.agent_results[agent_name] = result

    async def summarize_execution(
        self,
        context: ExecutionContext,
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

        result = await response_agent.execute(context)
        if result.status == "success":
            if not isinstance(result.payload, (str, AsyncGenerator)):
                return "Sorry, the response agent returned an invalid payload."
            return result.payload
        return "Sorry, unable to generate a response."

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
