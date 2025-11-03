"""
Base Agent interface for all agents in the system
"""
import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from maru_lang.models.agents import AgentResult
from maru_lang.pluggable.models import AgentConfig
from maru_lang.enums.agents import LLMFallbackStrategy
from maru_lang.pipelines.base import PipelineMessage
from maru_lang.dependencies.llm import (
    get_llm_manager,
    get_llm,
    LLMServerClient,
)


class BaseAgent(ABC):
    """
    Base class for all agents
    Each agent is responsible for a specific capability (tool)
    """

    def __init__(
        self,
        name: str,
        config: AgentConfig,
    ):
        self.name = name
        self.config = config
        self._initialized = False
        self._progress_queue: Optional[asyncio.Queue] = None

    async def initialize(self) -> None:
        """Initialize the agent (connect to services, load models, etc.)"""
        if not self._initialized:
            await self._setup()
            self._initialized = True

    @abstractmethod
    async def _setup(self) -> None:
        """Agent-specific initialization logic"""
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> AgentResult:
        """
        Execute the agent's main task

        Args:
            **kwargs: Agent-specific parameters (including progress_queue)

        Returns:
            AgentResult with the execution outcome
        """
        pass

    def set_progress_queue(self, queue: Optional[asyncio.Queue]) -> None:
        """
        Set the progress queue for this agent

        Args:
            queue: asyncio.Queue for sending progress messages
        """
        self._progress_queue = queue

    async def log_info(self, message: str, data: Any = None) -> None:
        """
        Send info message to progress queue

        Args:
            message: Info message to send
            data: Optional data to attach
        """
        if self._progress_queue:
            await self._progress_queue.put(
                PipelineMessage.info(f"[{self.name}] {message}", data=data)
            )

    async def log_warning(self, message: str, data: Any = None) -> None:
        """
        Send warning message to progress queue

        Args:
            message: Warning message to send
            data: Optional data to attach
        """
        if self._progress_queue:
            await self._progress_queue.put(
                PipelineMessage.warning(f"[{self.name}] ⚠️  {message}", data=data)
            )

    async def log_error(self, message: str, data: Any = None) -> None:
        """
        Send error message to progress queue

        Args:
            message: Error message to send
            data: Optional data to attach
        """
        if self._progress_queue:
            await self._progress_queue.put(
                PipelineMessage.error(f"[{self.name}] ❌ {message}", data=data)
            )

    def get_capabilities(self) -> Dict[str, Any]:
        """
        Return agent capabilities for discovery/documentation

        Loads from YAML config by default. Subclasses can override to add/modify capabilities.

        Returns:
            Dictionary describing what this agent can do
        """
        # YAML에서 기본 capabilities 로드
        yaml_capabilities = {
            "name": self.config.name,
            "description": self.config.description,
            "version": self.config.version,
            "priority": self.config.priority,
            "examples": self.config.examples or [],
        }

        # tools (parameters/outputs) 정보 추가
        if self.config.tools:
            yaml_capabilities["tools"] = {
                tool_name: tool_config.to_dict(tool_name)
                for tool_name, tool_config in self.config.tools.items()
            }

        # selection_criteria 추가
        if self.config.selection_criteria:
            yaml_capabilities["selection_criteria"] = {
                "keywords": self.config.selection_criteria.keywords,
                "patterns": self.config.selection_criteria.patterns,
            }

        # 서브클래스가 오버라이드했는지 확인
        subclass_capabilities = self._get_override_capabilities()

        # YAML 값과 오버라이드 값 병합 (오버라이드 우선)
        if subclass_capabilities:
            return {**yaml_capabilities, **subclass_capabilities}

        return yaml_capabilities

    def _get_override_capabilities(self) -> Optional[Dict[str, Any]]:
        """
        Subclasses can override this to provide additional/custom capabilities

        Returns:
            Dictionary with additional/override capabilities, or None
        """
        return None

    def get_override_params(self) -> Dict[str, Any]:
        """Get override params"""
        override_params = self.config.target_llm_config.override_params
        override_params_dict = {}
        if override_params.temperature:
            override_params_dict["temperature"] = override_params.temperature
        if override_params.max_tokens:
            override_params_dict["max_tokens"] = override_params.max_tokens
        if override_params.top_p:
            override_params_dict["top_p"] = override_params.top_p
        if override_params.timeout:
            override_params_dict["timeout"] = override_params.timeout
        return override_params_dict

    async def get_llm_client(self) -> LLMServerClient:
        """Get LLM client"""
        target_llm_config = self.config.target_llm_config
        if not target_llm_config:
            return await get_llm()

        if not target_llm_config.server_name:
            return await get_llm()

        llm_manager = await get_llm_manager()
        llm_client = llm_manager.get_server_by_name(target_llm_config.server_name)
        if not llm_client:
            if target_llm_config.fallback_strategy == LLMFallbackStrategy.ERROR:
                raise ValueError(f"LLM client not found for server name: {target_llm_config.server_name}")
            elif target_llm_config.fallback_strategy == LLMFallbackStrategy.ANY_AVAILABLE:
                return await get_llm()
            else:
                raise ValueError(f"Unknown fallback strategy: {target_llm_config.fallback_strategy}")
        return llm_client

    async def _get_llm_clients_with_fallback(self) -> list[LLMServerClient]:
        """
        Get list of LLM clients to try in order

        Returns:
            List of LLM clients in priority order (target first, then fallbacks)
        """
        llm_manager = await get_llm_manager()
        clients = []

        target_llm_config = self.config.target_llm_config

        # 1. Try target LLM first if specified
        if target_llm_config and target_llm_config.server_name:
            target_client = llm_manager.get_server_by_name(target_llm_config.server_name)
            if target_client:
                clients.append(target_client)

        # 2. Add fallback LLMs if strategy allows
        if target_llm_config and target_llm_config.fallback_strategy == LLMFallbackStrategy.ANY_AVAILABLE:
            # Get all available LLM servers
            all_servers = llm_manager.all_servers
            for server in all_servers:
                # Skip if already added as target
                if target_llm_config.server_name and server.config.name == target_llm_config.server_name:
                    continue
                clients.append(server)

        # 3. If no clients found, try to get any available
        if not clients:
            default_client = await get_llm()
            if default_client:
                clients.append(default_client)

        return clients

    async def request_with_fallback(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Make LLM request with automatic fallback to other LLMs

        Args:
            user_prompt: User prompt
            system_prompt: System prompt (optional)
            **kwargs: Additional parameters (temperature, max_tokens, etc.)

        Returns:
            LLM response text

        Raises:
            Exception: If all LLMs fail
        """
        clients = await self._get_llm_clients_with_fallback()

        if not clients:
            await self.log_error("No LLM clients available")
            raise ValueError("No LLM clients available")

        last_error = None
        for idx, client in enumerate(clients):
            try:
                # Log which LLM is being used
                if idx == 0:
                    await self.log_info(f"Using LLM: {client.config.name}")
                else:
                    await self.log_warning(f"Trying fallback LLM: {client.config.name}")

                response = await client.request(
                    user_prompt=user_prompt,
                    system_prompt=system_prompt,
                    **kwargs
                )

                if idx > 0:
                    await self.log_info(f"Fallback to LLM '{client.config.name}' succeeded")

                return response

            except Exception as e:
                last_error = e
                if idx < len(clients) - 1:
                    await self.log_warning(f"LLM '{client.config.name}' failed, trying next: {str(e)}")
                else:
                    await self.log_error(f"LLM '{client.config.name}' failed: {str(e)}")
                continue

        # All LLMs failed
        error_msg = f"All LLMs failed. Last error: {last_error}"
        await self.log_error(error_msg)
        raise Exception(f"All LLMs failed for agent {self.name}. Last error: {last_error}")

    async def request_with_tools_and_fallback(
        self,
        messages: list,
        tools: list,
        tool_choice: str = "auto",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Make LLM request with tools and automatic fallback

        Args:
            messages: List of messages
            tools: List of tool definitions
            tool_choice: Tool choice strategy
            **kwargs: Additional parameters

        Returns:
            Response dictionary with tool_calls

        Raises:
            Exception: If all LLMs fail
        """
        clients = await self._get_llm_clients_with_fallback()

        if not clients:
            await self.log_error("No LLM clients available")
            raise ValueError("No LLM clients available")

        last_error = None
        for idx, client in enumerate(clients):
            try:
                # Log which LLM is being used
                if idx == 0:
                    await self.log_info(f"Using LLM with tools: '{client.config.name}'")
                else:
                    await self.log_warning(f"Trying fallback LLM with tools: {client.config.name}")

                response = await client.request_with_tools(
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    **kwargs
                )

                if idx > 0:
                    await self.log_info(f"Fallback to LLM '{client.config.name}' succeeded")

                return response

            except Exception as e:
                last_error = e
                if idx < len(clients) - 1:
                    await self.log_warning(f"LLM '{client.config.name}' failed, trying next: {str(e)}")
                else:
                    await self.log_error(f"LLM '{client.config.name}' failed: {str(e)}")
                continue

        # All LLMs failed
        error_msg = f"All LLMs failed. Last error: {last_error}"
        await self.log_error(error_msg)
        raise Exception(f"All LLMs failed for agent {self.name}. Last error: {last_error}")

    async def cleanup(self) -> None:
        """Clean up resources when agent is no longer needed"""
        if self._initialized:
            await self._teardown()
            self._initialized = False

    async def _teardown(self) -> None:
        """Agent-specific cleanup logic"""
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}')"
