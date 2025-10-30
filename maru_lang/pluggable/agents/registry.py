"""
Agent Registry -
Discovers and loads agents
Dynamic agent registration and discovery
"""
import os
import sys
import json
import importlib.util
from pathlib import Path
from typing import Dict, List, Optional, Any, Type
from maru_lang.pluggable.agents.mcp_client_agent import MCPClientAgent
from maru_lang.configs.manager import get_config_manager
from maru_lang.pluggable.agents.base import BaseAgent
from maru_lang.pluggable.models import AgentConfig


class AgentRegistry:
    """
    Central registry for all agents
    Supports dynamic loading from user-defined directories
    """

    _instance = None

    def __new__(cls):
        """Singleton pattern"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._agents: Dict[str, Type[BaseAgent]] = {}
            self._agent_configs: Dict[str, AgentConfig] = {}
            self._initialized = True
            self.load_all()

    def load_all(self) -> List[str]:
        """Load agents from YAML configurations with Python implementations"""
        loaded_agents = []

        try:
            # Get configured agents from config manager
            config_manager = get_config_manager()
            config_manager.ensure_loaded()
            enabled_agents = config_manager.get_enabled_agents()
            for agent_name, agent_config in enabled_agents.items():
                # Handle MCP agents differently
                if agent_config.type == "mcp_client":
                    # Use SimpleMCPAgent directly
                    if agent_config.mcp_config:
                        try:
                            # Register SimpleMCPAgent with the config
                            self.register(
                                agent_name, MCPClientAgent, agent_config)
                            loaded_agents.append(agent_name)
                        except Exception as e:
                            print(f"Error loading MCP agent {agent_name}: {e}")
                    continue

                # Check if agent has an implementation
                if not agent_config.implementation:
                    print(
                        f"Agent {agent_name} has no implementation specified, skipping")
                    continue

                # Try to load the implementation
                try:
                    # Parse implementation path (e.g., "calculator_agent.CalculatorAgent" or "builtin.knowledge_search.KnowledgeSearchAgent")
                    impl_parts = agent_config.implementation.split('.')
                    # e.g., "calculator_agent" or "builtin.knowledge_search"
                    module_path = '.'.join(impl_parts[:-1])
                    class_name = impl_parts[-1]  # e.g., "CalculatorAgent"

                    # Determine implementation file location based on agent type
                    impl_file = None

                    if module_path.startswith("builtin."):
                        # Builtin agents: Python in pluggable/agents/builtin, YAML in maru_app/agents/builtin
                        builtin_dir = Path(__file__).parent / "builtin"
                        file_name = module_path.split(".", 1)[1] + ".py"  # Remove "builtin." prefix
                        impl_file = builtin_dir / file_name
                    elif module_path.startswith("mcps."):
                        # MCP agents are in agents/mcps/
                        user_agents_dir = Path.cwd() / "maru_app" / "agents"
                        # mcps.something -> mcps/something.py
                        file_name = module_path.replace(".", "/") + ".py"
                        impl_file = user_agents_dir / file_name
                    elif module_path.startswith("rerankers."):
                        # Reranker agents are in rerankers/ directory
                        rerankers_dir = Path.cwd() / "maru_app" / "rerankers"
                        file_name = module_path.split(".", 1)[1] + ".py"  # Remove "rerankers." prefix
                        impl_file = rerankers_dir / file_name
                    else:
                        # Default: all other agents are directly in agents/ directory
                        user_agents_dir = Path.cwd() / "maru_app" / "agents"
                        # Support both "agent_name" and "agents.agent_name" format
                        if module_path.startswith("agents."):
                            file_name = module_path[7:] + ".py"  # Remove "agents." prefix
                        else:
                            file_name = module_path + ".py"
                        impl_file = user_agents_dir / file_name

                    if impl_file and impl_file.exists():
                        # Load the module from file
                        spec = importlib.util.spec_from_file_location(
                            module_path, impl_file)
                        if spec and spec.loader:
                            module = importlib.util.module_from_spec(spec)
                            sys.modules[module_path] = module
                            spec.loader.exec_module(module)

                            # Get the class from the module
                            if hasattr(module, class_name):
                                agent_class = getattr(module, class_name)

                                # Register the agent
                                self.register(
                                    agent_name, agent_class, agent_config)
                                loaded_agents.append(agent_name)
                            else:
                                print(
                                    f"Class {class_name} not found in {impl_file}")
                    else:
                        print(
                            f"Implementation file not found: {impl_file}")

                except Exception as e:
                    print(f"Error loading agent {agent_name}: {e}")

        except Exception as e:
            print(f"Error loading configured agents: {e}")

        return loaded_agents

    def register(
        self,
        name: str,
        agent_class: Type[BaseAgent],
        config: AgentConfig
    ) -> None:
        """
        Register an agent

        Args:
            name: Unique agent name
            agent_class: Agent class (must inherit from BaseAgent)
            config: Optional agent configuration
        """
        if not issubclass(agent_class, BaseAgent):
            raise ValueError(f"{agent_class} must inherit from BaseAgent")
        self._agents[name] = agent_class
        self._agent_configs[name] = config

    def unregister(self, name: str) -> None:
        """Remove an agent from registry"""
        self._agents.pop(name, None)
        self._agent_configs.pop(name, None)

    def get_agent_class(self, name: str) -> Optional[Type[BaseAgent]]:
        """Get agent class by name"""
        return self._agents.get(name)

    def get_agent_config(self, name: str) -> Optional[AgentConfig]:
        """Get agent configuration by name"""
        return self._agent_configs.get(name)

    def list_agents(self) -> List[str]:
        """List all registered agent names"""
        return list(self._agents.keys())

    def get_all_agents(self) -> Dict[str, Type[BaseAgent]]:
        """Get all registered agents"""
        return self._agents.copy()

    def reload(self) -> None:
        """Reload all agents"""
        self.clear()
        self.load_all()

    def clear(self) -> None:
        """Clear all registered agents"""
        self._agents.clear()
        self._agent_configs.clear()


def get_registry() -> AgentRegistry:
    """Get the global agent registry instance"""
    return AgentRegistry()
