"""
Agent Executor/Orchestrator - Manages agent execution
"""
import asyncio
from typing import Dict, Any, List, Optional, Type
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

    async def _initialize_agent(
        self,
        agent_name: str,
        progress_queue: Optional[asyncio.Queue] = None
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
                if progress_queue:
                    await progress_queue.put(
                        PipelineMessage.info(f"✓ Agent '{agent_name}' initialized successfully")
                    )
                return True, None
            except Exception as e:
                error_msg = f"Failed to initialize agent '{agent_name}': {str(e)}"
                if progress_queue:
                    await progress_queue.put(
                        PipelineMessage.error(f"❌ {error_msg}")
                    )
                return False, error_msg

        return True, None

    async def execute(
        self,
        selection: AgentSelection,
        execution_context: ExecutionContext
    ) -> ExecutionResult:
        """
        Execute selected agents according to strategy

        Args:
            selection: Agent selection result
            execution_context: Context data for agents (question, user, etc.)
            strategy: Execution strategy ("sequential", "parallel", "conditional")

        Returns:
            ExecutionResult with all agent outputs
        """
        agent_results = {}
        errors = {}
        executed_order = []
        progress_queue = execution_context.progress_queue

        # Send start message
        if progress_queue:
            await progress_queue.put(
                PipelineMessage.info(f"Initializing agents: {', '.join(selection.selected_agents)}")
            )

        # Initialize all selected agents
        for agent_name in selection.selected_agents:
            if agent_name not in self.agent_registry:
                error_msg = f"Agent '{agent_name}' not registered (available: {', '.join(list(self.agent_registry.keys()))})"
                errors[agent_name] = error_msg
                if progress_queue:
                    await progress_queue.put(
                        PipelineMessage.error(error_msg)
                    )
                continue

            success, error = await self._initialize_agent(agent_name, progress_queue)
            if not success:
                errors[agent_name] = error or f"Failed to initialize agent: {agent_name}"

        # Prepare agent-specific parameters from selection
        agent_params = selection.parameters or {}

        # Use execution_order if provided, otherwise fall back to selected_agents
        execution_order = selection.execution_order if selection.execution_order else selection.selected_agents

        if progress_queue:
            await progress_queue.put(
                PipelineMessage.info(f"Executing agents in order: {' → '.join(execution_order)}")
            )

        # Execute agents sequentially
        try:
            agent_results, executed_order = await self._execute_sequential(
                execution_order,
                execution_context,
                agent_params,
                errors
            )
        except Exception as e:
            error_msg = f"Execution failed: {str(e)}"
            if progress_queue:
                await progress_queue.put(
                    PipelineMessage.error(error_msg)
                )
            # Use last agent name if available, otherwise 'unknown'
            last_agent = execution_order[-1] if execution_order else "unknown"
            errors[last_agent] = error_msg

        return ExecutionResult(
            agent_results=agent_results,
            execution_order=executed_order,
            success=len(errors) == 0 and len(agent_results) > 0,
            errors=errors
        )

    async def _execute_sequential(
        self,
        execution_order: List[str],
        context: ExecutionContext,
        params: Dict[str, Any],
        errors: Dict[str, str]
    ) -> tuple[Dict[str, AgentResult], List[str]]:
        """
        Execute agents sequentially, chaining results as input to next agent.
        Stops execution if any agent fails.
        """
        results = {}
        executed = []
        progress_queue = context.progress_queue

        # Save original question before any modification
        if "original_question" not in context.metadata:
            context.metadata["original_question"] = context.question

        for agent_name in execution_order:
            if agent_name in errors:
                # Agent failed to initialize, stop execution
                if progress_queue:
                    await progress_queue.put(
                        PipelineMessage.warning(
                            f"⚠️  Skipping agent '{agent_name}' due to initialization error"
                        )
                    )
                break

            agent = self.agent_registry.get(agent_name)
            if not agent:
                error_msg = f"Agent not found: {agent_name}"
                errors[agent_name] = error_msg
                if progress_queue:
                    await progress_queue.put(
                        PipelineMessage.error(error_msg)
                    )
                break

            try:
                # Set progress queue on agent
                agent.set_progress_queue(progress_queue)

                # Notify agent execution start
                if progress_queue:
                    await progress_queue.put(
                        PipelineMessage.info(f"▶️  Executing agent '{agent_name}'...")
                    )

                # Merge context with agent-specific params
                agent_context = context.to_dict()
                if agent_name in params:
                    agent_context.update(params[agent_name])

                # Execute agent
                result = await agent.execute(**agent_context)
                results[agent_name] = result
                executed.append(agent_name)

                # If agent failed, stop execution chain
                if not result.success:
                    error_msg = result.error or "Agent execution failed"
                    errors[agent_name] = error_msg
                    if progress_queue:
                        await progress_queue.put(
                            PipelineMessage.error(
                                f"Agent '{agent_name}' failed: {error_msg}"
                            )
                        )
                    break

                # Success notification
                if progress_queue:
                    await progress_queue.put(
                        PipelineMessage.info(f"✓ Agent '{agent_name}' completed successfully")
                    )

                # Chain result to next agent: update question with current result
                if result.result:
                    context.question = result.result  # Next agent receives this as input
                    # Also store in metadata for reference
                    context.metadata[f"{agent_name}_result"] = result.result
                    if result.data:
                        context.metadata[f"{agent_name}_data"] = result.data

            except Exception as e:
                error_msg = f"Exception in agent {agent_name}: {str(e)}"
                errors[agent_name] = str(e)
                results[agent_name] = AgentResult(
                    success=False,
                    result="",
                    error=str(e)
                )
                if progress_queue:
                    await progress_queue.put(
                        PipelineMessage.error(error_msg)
                    )
                # Stop execution on exception
                break

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
