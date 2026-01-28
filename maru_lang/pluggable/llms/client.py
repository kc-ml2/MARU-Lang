from __future__ import annotations
import asyncio
from typing import AsyncGenerator, Optional, List, Dict, Any, Union, Literal, overload
from any_llm import AnyLLM
from any_llm.types.completion import ChatCompletion
from maru_lang.pluggable.models import LLMConfig
from maru_lang.configs.system_config import get_system_config


class LLMClient:
    """Unified LLM client using any-llm library."""

    def __init__(self, config: Union[LLMConfig, dict]):
        if isinstance(config, dict):
            self.config = LLMConfig(**config)
        else:
            self.config = config

        # Create any-llm client
        self.client = AnyLLM.create(
            self.config.provider,
            api_key=self.config.api_key,
            api_base=self.config.base_url
        )

    def _get_timeout(self, timeout: Optional[float] = None) -> float:
        """Get effective timeout value with priority: request > config > system default."""
        if timeout is not None:
            return timeout
        if self.config.timeout is not None:
            return self.config.timeout
        return get_system_config().llm.default_timeout

    @overload
    async def request(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
        stream: Literal[False] = False,
        timeout: Optional[float] = None,
        **kwargs
    ) -> str: ...

    @overload
    async def request(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
        stream: Literal[True] = ...,
        timeout: Optional[float] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]: ...

    async def request(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
        timeout: Optional[float] = None,
        **kwargs
    ) -> Union[str, AsyncGenerator[str, None]]:
        """Send a request to the LLM.

        Args:
            system_prompt: System prompt used when messages is omitted.
            user_prompt: User prompt used when messages is omitted.
            messages: Explicit message list to send to the LLM.
            stream: If True, returns an async generator yielding chunks.
            timeout: Request timeout in seconds. Falls back to config.timeout,
                then system default (llm.default_timeout in system_config.yaml).
            **kwargs: Additional parameters such as temperature or max_tokens.

        Returns:
            The LLM response content as a string, or async generator if streaming.

        Raises:
            asyncio.TimeoutError: If the request exceeds the timeout.
        """
        if messages is None:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

        # Merge config defaults with overrides
        params = {**self.config.config, **kwargs}
        params["stream"] = stream

        effective_timeout = self._get_timeout(timeout)

        try:
            response = await asyncio.wait_for(
                self.client.acompletion(
                    model=self.config.model_name,
                    messages=messages,  # type: ignore
                    **params
                ),
                timeout=effective_timeout
            )
        except asyncio.TimeoutError:
            raise asyncio.TimeoutError(
                f"LLM request timed out after {effective_timeout}s"
            )
        except Exception as e:
            print(f"LLM request failed: {e}")
            raise e

        if stream:
            return self._stream_response(response)
        else:
            if not isinstance(response, ChatCompletion):
                raise ValueError("Expected ChatCompletion response type")
            return response.choices[0].message.content or ""

    async def _stream_response(
        self,
        response: Any
    ) -> AsyncGenerator[str, None]:
        """Process streaming response and yield content chunks."""
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def request_with_tools(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Union[str, Dict[str, Any]] = "auto",
        timeout: Optional[float] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Send a request that allows tool usage.

        Args:
            system_prompt: System prompt used when messages is omitted.
            user_prompt: User prompt used when messages is omitted.
            messages: Explicit message list to send to the LLM.
            tools: Tool definitions available to the LLM.
            tool_choice: Tool selection mode.
            timeout: Request timeout in seconds. Falls back to config.timeout,
                then system default (llm.default_timeout in system_config.yaml).
            **kwargs: Additional parameters for the request.

        Returns:
            Dict with content and tool_calls keys.

        Raises:
            asyncio.TimeoutError: If the request exceeds the timeout.
        """
        if messages is None:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

        params = {**self.config.config, **kwargs}

        if tools:
            params["tools"] = tools
            params["tool_choice"] = tool_choice

        params["stream"] = False  # Tool calls not supported in streaming mode

        effective_timeout = self._get_timeout(timeout)

        try:
            response = await asyncio.wait_for(
                self.client.acompletion(
                    model=self.config.model_name,
                    messages=messages,  # type: ignore
                    **params
                ),
                timeout=effective_timeout
            )
        except asyncio.TimeoutError:
            raise asyncio.TimeoutError(
                f"LLM request timed out after {effective_timeout}s"
            )

        if not isinstance(response, ChatCompletion):
            raise ValueError("Expected ChatCompletion response type")

        message = response.choices[0].message

        # Convert tool_calls objects to dict format
        tool_calls_dict = []
        for tc in (message.tool_calls or []):
            func = getattr(tc, 'function', None)
            if func:
                tool_calls_dict.append({
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": func.name,
                        "arguments": func.arguments
                    }
                })

        return {
            "content": message.content or "",
            "tool_calls": tool_calls_dict
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LLMClient):
            return NotImplemented
        return self.config.name == other.config.name

    def __hash__(self) -> int:
        return hash(self.config.name)
