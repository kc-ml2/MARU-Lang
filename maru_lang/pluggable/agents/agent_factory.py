"""
Agent Factory - Creates and configures agents based on configuration
"""
from typing import Dict, Optional, List
from maru_lang.pluggable.agents.base import BaseAgent
from maru_lang.pluggable.agents.registry import get_registry
from maru_lang.configs.manager import get_config_manager
from maru_lang.pluggable.models import AgentConfig
from maru_lang.pluggable.agents.mcp_client_agent import MCPClientAgent


class AgentFactory:
    """
    Factory for creating agents with proper configuration
    Supports dynamic loading
    """

    def __init__(
        self,
    ):
        """
        Initialize factory with default components
        """
        self.config_manager = get_config_manager()
        self.registry = get_registry()

    def create_agent(
        self,
        agent_name: str,
        agent_config: AgentConfig
    ) -> BaseAgent:
        """
        Create an agent instance based on name and configuration

        Args:
            agent_name: Name/type of the agent
            agent_config: Agent-specific configuration

        Returns:
            Agent instance or None if not found
        """
        # Get agent class from registry
        agent_class = self.registry.get_agent_class(agent_name)
        if not agent_class:
            raise ValueError(f"Agent class not found for: {agent_name}")

        if issubclass(agent_class, MCPClientAgent):
            # Other MCP agents need name, server_params, and llm_client
            if not agent_config.mcp_config:
                raise ValueError(
                    f"MCP agent {agent_name} missing mcp_config")
        return agent_class(
            name=agent_name,
            config=agent_config,  # Pass full agent_config as config
        )

    def create_agents_from_config(self) -> Dict[str, BaseAgent]:
        """
        Create all agents based on configuration

        Returns:
            Dictionary of agent instances by name
        """
        agents = {}

        # Create all agents from the registry
        for agent_name in self.registry.list_agents():
            agent_config = self.registry.get_agent_config(agent_name)
            if not agent_config:
                print(
                    f"[ERROR AgentFactory] Agent config not found: {agent_name}")
                continue
            agent = self.create_agent(agent_name, agent_config)
            if agent:
                agents[agent_name] = agent
            else:
                print(
                    f"[ERROR AgentFactory] Failed to create agent: {agent_name}")
                raise Exception(f"Failed to create agent: {agent_name}")
        return agents

    def list_available_agents(self) -> List[str]:
        """List all available agent names"""
        return self.registry.list_agents()

    def reload_agents(self) -> None:
        """Reload all agents from sources"""
        self.registry.reload()
