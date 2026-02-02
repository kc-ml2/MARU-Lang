"""
Agent Selector - Responsible only for selecting which agents to use
(Previously Supervisor, now focused only on selection)
"""
import json
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from maru_lang.models.agents import AgentSelection
from maru_lang.configs.manager import get_config_manager
from maru_lang.models.chat import ChatHistory
from maru_lang.dependencies.llm import get_llm_manager
from maru_lang.pluggable.llms import LLMClient


class SelectorConstants:
    """Constants for AgentSelector"""
    DEFAULT_TEMPERATURE = 0.1
    TOOL_NAME = "select_agents"
    HISTORY_CONTEXT_LIMIT = 5
    USE_PREFIX = "use_"
    CONFIG_FILE = "build_selector.yaml"


class AgentSelector:
    """
    Selects appropriate agents based on user query analysis
    This is the refactored Supervisor that only handles selection
    """

    def __init__(self):
        """Initialize Agent Selector with LLM clients for fallback"""
        self.config_manager = get_config_manager()
        self.selector_config = self._load_selector_config()

        # Store available LLM clients will be loaded lazily
        self.llm_clients: List[LLMClient] = []

    def _load_selector_config(self) -> Dict[str, Any]:
        """Load selector configuration from YAML file"""
        config_path = Path.cwd() / "maru_app" / SelectorConstants.CONFIG_FILE

        if not config_path.exists():
            raise FileNotFoundError(
                f"{SelectorConstants.CONFIG_FILE} not found in {config_path}")

        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        if config is None:
            raise ValueError(
                f"Empty or invalid configuration file: {config_path}")

        return self._build_dynamic_config(config)

    def _get_llm_clients_with_fallback(self) -> List[LLMClient]:
        """Get list of LLM clients to try in order (lazy load)"""
        if not self.llm_clients:
            llm_manager = get_llm_manager()
            self.llm_clients = llm_manager.clients

            if not self.llm_clients:
                raise ValueError("No LLM clients available for Agent Selector")

        return self.llm_clients

    def _build_dynamic_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Build available_agents dynamically from loaded agents"""
        enabled_agents = self.config_manager.get_enabled_agents()
        agent_overrides = config.get("agent_overrides", {})
        if not agent_overrides:
            agent_overrides = {}
        available_agents = []

        # Selectable builtin agents (builtin but can be selected by agent selector)
        selectable_builtins = {"knowledge_search"}

        for agent_config in enabled_agents.values():
            agent_name = agent_config.name

            # Skip builtin agents except selectable ones, and skip utility agents
            # Utility agents (rerankers, etc.) are not selectable for general tasks
            is_selectable = (agent_config.type not in ("builtin", "utility") or
                             agent_name in selectable_builtins)

            if agent_overrides.get(agent_name, True) and is_selectable:
                available_agents.append({
                    "name": agent_name,
                    "description": agent_config.description or f"{agent_name} agent",
                    "enabled": True
                })

        config["available_agents"] = available_agents
        return config

    async def select_agents(
        self,
        question: str,
        chat_history: Optional[ChatHistory] = None,
        stream: bool = True
    ) -> Optional[AgentSelection]:
        """
        Select appropriate agents based on question analysis
        Tries multiple LLMs if available for fallback

        Args:
            question: User's question
            chat_history: Previous conversation history

        Returns:
            AgentSelection with selected agents, or None if selection fails
        """
        self.config_manager.ensure_loaded()

        # Build request components once
        tools = self._build_selection_tools()
        messages = self._build_messages(question, chat_history)
        temperature = self._get_temperature()

        # Get available LLM clients
        clients = self._get_llm_clients_with_fallback()

        # Try each available LLM until one succeeds
        for client in clients:
            try:
                # Make LLM request with tools
                # Force the use of select_agents function
                tool_choice = {
                    "type": "function",
                    "function": {"name": SelectorConstants.TOOL_NAME}
                }
                response = await client.request_with_tools(
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    stream=stream
                )

                # Parse response and create selection
                result = self._parse_response(response)
                # Check if we got a valid selection
                return result
            except Exception as e:
                continue
        # All LLMs failed
        return None

    def _build_messages(
        self,
        question: str,
        chat_history: Optional[ChatHistory] = None
    ) -> List[Dict[str, Any]]:
        """Build messages for the selection request"""
        system_prompt = self._get_system_prompt()
        user_prompt = self._build_user_prompt(question, chat_history)
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

    def _build_user_prompt(
        self,
        question: str,
        chat_history: Optional[ChatHistory] = None
    ) -> str:
        """Build user prompt with question and chat history"""
        # Build chat history context
        history_text = chat_history.to_string(
            SelectorConstants.HISTORY_CONTEXT_LIMIT,
            True,
        ) if chat_history else None

        # Get user prompt template from config
        user_prompt_template = self.selector_config.get("user_prompt")
        if not user_prompt_template:
            raise ValueError(
                f"user_prompt not found in {SelectorConstants.CONFIG_FILE}")
        # Format with variables
        return user_prompt_template.format(
            question=question,
            history_text=history_text if history_text else "No previous conversation"
        )

    def _get_temperature(self) -> float:
        """Get temperature parameter from config"""
        parameters = self.selector_config.get('parameters', {})
        return parameters.get('temperature', SelectorConstants.DEFAULT_TEMPERATURE)

    def _parse_response(self, response: Dict[str, Any]) -> Optional[AgentSelection]:
        """Parse LLM response and create AgentSelection"""
        if not response or 'tool_calls' not in response:
            return None

        tool_calls = response.get('tool_calls', [])
        if not tool_calls:
            # LLM returned content instead of tool calls - try to parse as JSON
            content = response.get('content', '').strip()
            if content:
                parsed = self._try_parse_content_as_selection(content)
                if parsed:
                    return parsed
            return None

        tool_call_args = self._extract_tool_arguments(tool_calls[0])
        selected_agents = self._extract_selected_agents(tool_call_args)

        execution_order = self._clean_execution_order(
            tool_call_args.get("execution_order", selected_agents)
        )

        if not selected_agents and execution_order:
            selected_agents = execution_order

        if not execution_order and selected_agents:
            execution_order = selected_agents

        return AgentSelection(
            selected_agents=selected_agents,
            execution_order=execution_order,
            reasoning=tool_call_args.get("reasoning", ""),
            parameters=tool_call_args.get("parameters", {})
        )

    def _try_parse_content_as_selection(self, content: str) -> Optional[AgentSelection]:
        """Fallback: parse content as JSON when LLM returns tool args in content instead of tool_calls"""
        try:
            tool_call_args = json.loads(content)
            if not isinstance(tool_call_args, dict):
                return None
        except json.JSONDecodeError:
            return None

        selected_agents = self._extract_selected_agents(tool_call_args)
        execution_order = self._clean_execution_order(
            tool_call_args.get("execution_order", selected_agents)
        )

        if not selected_agents and execution_order:
            selected_agents = execution_order
        if not execution_order and selected_agents:
            execution_order = selected_agents

        return AgentSelection(
            selected_agents=selected_agents,
            execution_order=execution_order,
            reasoning=tool_call_args.get("reasoning", ""),
            parameters=tool_call_args.get("parameters", {})
        )

    def _extract_tool_arguments(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """Extract arguments from tool call, handling different response formats"""
        # Handle different response formats
        if 'function' in tool_call:
            # Standard OpenAI format
            arguments = tool_call['function'].get('arguments', {})
        else:
            # Direct format
            arguments = tool_call.get('arguments', {})

        # Parse arguments if it's a string
        if isinstance(arguments, str):
            return json.loads(arguments)
        else:
            return arguments

    def _extract_selected_agents(self, tool_args: Dict[str, Any]) -> List[str]:
        """Extract selected agents from tool call arguments"""
        selected_agents = []
        for agent in self._get_available_agents():
            agent_name = agent["name"]
            if tool_args.get(f"{SelectorConstants.USE_PREFIX}{agent_name}", False):
                selected_agents.append(agent_name)
        return selected_agents

    def _clean_execution_order(self, execution_order: Union[List[str], str]) -> List[str]:
        """Clean execution order by removing use_ prefix if present"""
        if not execution_order:
            return []

        # Parse if it's a JSON string
        if isinstance(execution_order, str):
            try:
                execution_order = json.loads(execution_order)
            except json.JSONDecodeError:
                return []

        cleaned_order = []
        for agent in execution_order:
            if isinstance(agent, str):
                # Remove 'use_' prefix if it exists
                if agent.startswith(SelectorConstants.USE_PREFIX):
                    cleaned_order.append(
                        agent[len(SelectorConstants.USE_PREFIX):])
                else:
                    cleaned_order.append(agent)
        return cleaned_order

    def _get_available_agents(self) -> List[Dict[str, Any]]:
        """Get list of available agents from config"""
        return [
            agent for agent in self.selector_config.get("available_agents", [])
            if agent.get("enabled", True)
        ]

    def _build_selection_tools(self) -> List[Dict[str, Any]]:
        """Build tools for agent selection"""
        properties = {}

        # Create a mapping of agent names to descriptions
        available_agents = self._get_available_agents()

        # Add boolean for each available agent with proper description
        for agent in available_agents:
            agent_name = agent["name"]
            description = agent["description"]
            properties[f"{SelectorConstants.USE_PREFIX}{agent_name}"] = {
                "type": "boolean",
                "description": f"Whether to use the {agent_name} agent: {description}"
            }

        # Add execution order
        properties["execution_order"] = {
            "type": "array",
            "items": {"type": "string"},
            "description": "Order in which to execute selected agents"
        }

        # Add reasoning
        properties["reasoning"] = {
            "type": "string",
            "description": "Explanation of why these agents were selected"
        }

        # Add optional parameters for agents
        properties["parameters"] = {
            "type": "object",
            "description": "Optional parameters for specific agents"
        }

        return [
            {
                "type": "function",
                "function": {
                    "name": SelectorConstants.TOOL_NAME,
                    "description": "Select appropriate agents to handle the user's question",
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": ["reasoning"]
                    }
                }
            }
        ]

    def _get_system_prompt(self) -> str:
        """Get system prompt from config with dynamic agent descriptions"""
        # Get system prompt template from config
        system_prompt_template = self.selector_config.get("system_prompt", "")

        # Build agent descriptions from config
        agent_descriptions = []
        for agent in self._get_available_agents():
            agent_name = agent["name"]
            agent_description = agent["description"]
            if agent.get("enabled", True):
                agent_descriptions.append(
                    f"- {agent_name}: {agent_description}")

        # Replace template with actual agent descriptions
        agent_descriptions_text = "\n".join(agent_descriptions)
        return system_prompt_template.format(agent_descriptions=agent_descriptions_text)

    def get_enabled_agents(self) -> List[str]:
        """Get list of enabled agents from config"""
        return [
            agent["name"] for agent in self._get_available_agents()
            if agent.get("enabled", True)
        ]
