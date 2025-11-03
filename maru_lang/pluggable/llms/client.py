from __future__ import annotations
import json
import asyncio
import httpx
from typing import Optional, List, Dict, Union
from maru_lang.configs import LLMConfig


class LLMServerClient:

    def __init__(
        self,
        config: Union[LLMConfig, dict]
    ):
        # Convert dictionaries into LLMConfig instances for compatibility
        if isinstance(config, dict):
            self.config = LLMConfig(**config)
        else:
            self.config = config
        # Reuse the HTTP client to minimize connection overhead
        self._http_client = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Return a reusable HTTP client instance."""
        if self._http_client is None or self._http_client.is_closed:
            headers = self.config.headers.copy() if self.config.headers else {}
            if self.config.api_key:
                headers['Authorization'] = f'Bearer {self.config.api_key}'

            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=5.0,    # Connection timeout
                    read=self.config.timeout,      # Read timeout
                    write=5.0,      # Write timeout
                    pool=5.0        # Pool timeout
                ),
                limits=httpx.Limits(
                    max_connections=20,          # Allow more concurrent connections
                    max_keepalive_connections=10  # Allow additional keepalive connections
                ),
                headers=headers
            )
        return self._http_client


    async def request(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        messages: Optional[List[Dict[str, str]]] = None,
        stream: bool = False,
        timeout: float = 30.0,
        **kwargs
    ):
        """Send a request to the LLM server.

        Args:
            system_prompt: System prompt used when ``messages`` is omitted.
            user_prompt: User prompt used when ``messages`` is omitted.
            messages: Explicit message list to send to the LLM.
            stream: Whether to request streaming responses.
            timeout: Per-request timeout.
            **kwargs: Additional parameters such as ``temperature`` or ``max_tokens``.
        """
        # Compose messages when none are provided
        if messages is None:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

        # Handle mock:// URLs by echoing the latest user message
        if self.config.url.startswith("mock://"):
            user_message = messages[-1]["content"] if messages else ""
            return f"Echo: {user_message}"

        # Build request payload by combining config defaults and overrides
        payload = {
            "stream": stream,
            "messages": messages,
            "model": self.config.model_name,
            **self.config.config,  # Default configuration (temperature, max_tokens, etc.)
            **kwargs  # Overrides
        }
        endpoint = self._build_endpoint(self.config.chat_completions_path)

        try:
            client = await self._get_http_client()
            response = await client.post(
                endpoint,
                json=payload,
                timeout=timeout if timeout != 30.0 else self.config.timeout
            )

            # Check response status
            if response.status_code != 200:
                error_text = response.text
                raise Exception(f"HTTP {response.status_code}: {error_text}")

            # Check if response has content
            response_text = response.text
            if not response_text.strip():
                raise Exception("Empty response from LLM server")

            try:
                data = response.json()
            except Exception as exc:
                raise Exception(
                    f"Invalid JSON response: {response_text[:200]}... ({exc})"
                )
            
            if "choices" not in data or len(data["choices"]) == 0:
                raise Exception("choices field not found")
                
            choice = data["choices"][0]
            message = choice.get("message", {})
            
            content = message.get("content", "")
            reasoning_content = message.get("reasoning_content", "")
            
            # Fall back to reasoning_content when content is empty, otherwise fail
            if content is not None and content.strip():
                result = content
            elif reasoning_content is not None and reasoning_content.strip():
                result = reasoning_content
            else:
                raise Exception("The LLM server returned an empty response.")
            
            return result
            
        except httpx.TimeoutException:
            raise Exception("The request took too long and was cancelled.")
        except Exception as e:
            raise Exception(f"An error occurred while processing the request: {str(e)}")

    async def request_with_tools(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        messages: Optional[List[Dict[str, str]]] = None,
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        timeout: float = 30.0,
        **kwargs
    ):
        """Send a request that allows tool usage.

        Args:
            system_prompt: System prompt used when ``messages`` is omitted.
            user_prompt: User prompt used when ``messages`` is omitted.
            messages: Explicit message list to send to the LLM.
            tools: Tool definitions available to the LLM.
            tool_choice: Tool selection mode ("auto", "none", or a specific tool name).
            timeout: Per-request timeout.
            **kwargs: Additional parameters for the request.

        Returns:
            Dict with ``content`` and ``tool_calls`` keys when tools are used.
        """
        # Compose messages when none are provided
        if messages is None:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

        # Build payload
        payload = {
            "stream": False,
            "messages": messages,
            "model": self.config.model_name,
            **self.config.config,
            **kwargs
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        endpoint = self._build_endpoint(self.config.chat_completions_path)

        try:
            client = await self._get_http_client()
            response = await client.post(
                endpoint,
                json=payload,
                timeout=timeout if timeout != 30.0 else self.config.timeout
            )

            # Check response status
            if response.status_code != 200:
                error_text = response.text
                raise Exception(f"HTTP {response.status_code}: {error_text}")

            # Check if response has content
            response_text = response.text
            if not response_text.strip():
                raise Exception("Empty response from LLM server")

            try:
                data = response.json()
            except Exception as exc:
                raise Exception(
                    f"Invalid JSON response: {response_text[:200]}... ({exc})"
                )

            if "choices" not in data or len(data["choices"]) == 0:
                raise Exception("choices field not found")

            message = data["choices"][0].get("message", {})

            # Return both content and tool_calls
            result = {
                "content": message.get("content", ""),
                "tool_calls": message.get("tool_calls", [])
            }

            # Parse tool call arguments if present
            for tool_call in result["tool_calls"]:
                if "function" in tool_call and "arguments" in tool_call["function"]:
                    args_str = tool_call["function"]["arguments"]
                    try:
                        tool_call["function"]["arguments"] = json.loads(args_str)
                    except json.JSONDecodeError:
                        tool_call["function"]["arguments"] = {}

            return result

        except httpx.TimeoutException:
            raise Exception("The request took too long and was cancelled.")
        except Exception as e:
            raise Exception(f"An error occurred while processing the request: {str(e)}")

    async def health_check(
        self,
        health_check_timeout: int = 5,
    ) -> bool:
        # Mock servers are always considered healthy
        if self.config.url.startswith("mock://"):
            return True

        try:
            client = await self._get_http_client()

            health_options = self.config.health_check or {}
            if health_options.get("enabled") is False:
                return True

            # The OpenAI API uses /v1/models for health checks
            if "api.openai.com" in self.config.url:
                if self.config.health_check_endpoint in ["/health", "/models", "", None]:
                    health_endpoint = "/v1/models"
                else:
                    health_endpoint = self.config.health_check_endpoint
            else:
                health_endpoint = self.config.health_check_endpoint or "/health"

            response = await client.get(
                self._build_endpoint(health_endpoint),
                timeout=health_check_timeout)

            if response.status_code == 200:
                return True
            else:
                print(f"Health check failed for {self.config.name}: HTTP {response.status_code}")
                return False
        except Exception as e:
            print(f"Health check error for {self.config.name}: {str(e)}")
            return False

    def _build_endpoint(self, path: str) -> str:
        """Construct request endpoint from base URL and path"""
        if not path:
            return self.config.url

        if path.startswith("http://") or path.startswith("https://"):
            return path

        base_url = self.config.url.rstrip('/')
        normalized_path = path if path.startswith('/') else f"/{path}"
        return f"{base_url}{normalized_path}"

    async def close(self):
        """Close the HTTP client safely."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    def __eq__(self, value: LLMServerClient):
        if not isinstance(value, LLMServerClient):
            return False
        return self.config.name == value.config.name

    def __hash__(self):
        return hash(self.config.name)

    def __del__(self):
        """Ensure the HTTP client is closed when the object is deleted."""
        if hasattr(self, '_http_client') and self._http_client and not self._http_client.is_closed:
            # Attempt to close the client in the background (may run in a sync context)
            try:
                loop = asyncio.get_running_loop()
                # Create task and suppress the unawaited coroutine warning
                task = loop.create_task(self._http_client.aclose())
                # Add a callback to prevent the warning about unawaited task
                task.add_done_callback(lambda t: None)
            except RuntimeError:
                # If there is no running loop, close synchronously
                try:
                    asyncio.run(self._http_client.aclose())
                except Exception:
                    # Ignore cleanup failures during interpreter shutdown
                    pass