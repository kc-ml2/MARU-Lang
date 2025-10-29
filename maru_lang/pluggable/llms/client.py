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
        # dict로 받은 경우 LLMConfig로 변환
        if isinstance(config, dict):
            self.config = LLMConfig(**config)
        else:
            self.config = config
        # HTTP 클라이언트를 재사용하여 연결 오버헤드 감소
        self._http_client = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """재사용 가능한 HTTP 클라이언트를 반환합니다."""
        if self._http_client is None or self._http_client.is_closed:
            headers = self.config.headers.copy() if self.config.headers else {}
            if self.config.api_key:
                headers['Authorization'] = f'Bearer {self.config.api_key}'

            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=5.0,    # 연결 타임아웃
                    read=self.config.timeout,      # 읽기 타임아웃
                    write=5.0,      # 쓰기 타임아웃
                    pool=5.0        # 풀 타임아웃
                ),
                limits=httpx.Limits(
                    max_connections=20,          # 더 많은 동시 연결 허용
                    max_keepalive_connections=10  # 더 많은 keepalive 연결
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
        """LLM 요청을 처리합니다.

        Args:
            system_prompt: 시스템 프롬프트 (messages가 없을 때 사용)
            user_prompt: 사용자 프롬프트 (messages가 없을 때 사용)
            messages: 직접 전달할 메시지 리스트
            stream: 스트리밍 여부
            timeout: 타임아웃 설정
            **kwargs: 추가 파라미터 (temperature, max_tokens 등)
        """
        # 메시지 구성
        if messages is None:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

        # Mock 서버 처리
        if self.config.url.startswith("mock://"):
            # 사용자의 마지막 메시지를 그대로 반환
            user_message = messages[-1]["content"] if messages else ""
            return f"Echo: {user_message}"

        # 페이로드 구성 - config의 기본 설정과 kwargs를 합침
        payload = {
            "stream": stream,
            "messages": messages,
            "model": self.config.model_name,
            **self.config.config,  # 기본 설정 (temperature, max_tokens 등)
            **kwargs  # 오버라이드
        }
        try:
            client = await self._get_http_client()
            response = await client.post(
                f"{self.config.url}/v1/chat/completions",
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
            except Exception as e:
                raise Exception(f"Invalid JSON response: {response_text[:200]}...")
            
            if "choices" not in data or len(data["choices"]) == 0:
                raise Exception("choices field not found")
                
            choice = data["choices"][0]
            message = choice.get("message", {})
            
            content = message.get("content", "")
            reasoning_content = message.get("reasoning_content", "")
            
            # content가 None이면 reasoning_content 사용, 둘 다 없으면 예외 발생
            if content is not None and content.strip():
                result = content
            elif reasoning_content is not None and reasoning_content.strip():
                result = reasoning_content
            else:
                raise Exception("LLM 서버에서 응답을 생성하지 못했습니다.")
            
            return result
            
        except httpx.TimeoutException:
            raise Exception("요청이 너무 오래 걸려서 중단했어요.")
        except Exception as e:
            raise Exception(f"요청 중 오류가 발생했어요: {str(e)}")

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
        """LLM 도구 요청을 처리합니다.

        Args:
            system_prompt: 시스템 프롬프트 (messages가 없을 때 사용)
            user_prompt: 사용자 프롬프트 (messages가 없을 때 사용)
            messages: 직접 전달할 메시지 리스트
            tools: 사용할 도구 정의
            tool_choice: 도구 선택 설정 ("auto", "none", or specific tool)
            timeout: 타임아웃 설정
            **kwargs: 추가 파라미터

        Returns:
            Dict with 'content' and 'tool_calls' if tools were called
        """
        # 메시지 구성
        if messages is None:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

        # 페이로드 구성
        payload = {
            "stream": False,
            "messages": messages,
            "model": self.config.model_name,
            **self.config.config,  # 기본 설정
            **kwargs  # 오버라이드
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        try:
            client = await self._get_http_client()
            response = await client.post(
                f"{self.config.url}/v1/chat/completions",
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
            except Exception as e:
                raise Exception(f"Invalid JSON response: {response_text[:200]}...")

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
            raise Exception("요청이 너무 오래 걸려서 중단했어요.")
        except Exception as e:
            raise Exception(f"요청 중 오류가 발생했어요: {str(e)}")

    async def health_check(
        self,
        health_check_timeout: int = 5,
    ) -> bool:
        # Mock 서버는 항상 healthy
        if self.config.url.startswith("mock://"):
            return True

        try:
            client = await self._get_http_client()

            # OpenAI API는 /v1/models 엔드포인트 사용
            if "api.openai.com" in self.config.url:
                if self.config.health_check_endpoint in ["/health", "/models"]:
                    health_endpoint = "/v1/models"
                else:
                    health_endpoint = self.config.health_check_endpoint
            else:
                health_endpoint = self.config.health_check_endpoint

            response = await client.get(
                f"{self.config.url}{health_endpoint}",
                timeout=health_check_timeout)

            if response.status_code == 200:
                return True
            else:
                print(f"Health check failed for {self.config.name}: HTTP {response.status_code}")
                return False
        except Exception as e:
            print(f"Health check error for {self.config.name}: {str(e)}")
            return False

    async def close(self):
        """HTTP 클라이언트를 안전하게 종료합니다."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    def __eq__(self, value: LLMServerClient):
        if not isinstance(value, LLMServerClient):
            return False
        return self.config.name == value.config.name

    def __hash__(self):
        return hash(self.config.name)

    def __del__(self):
        """객체가 삭제될 때 HTTP 클라이언트도 정리합니다."""
        if hasattr(self, '_http_client') and self._http_client and not self._http_client.is_closed:
            # 백그라운드에서 정리 (동기적 컨텍스트에서 호출될 수 있음)
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._http_client.aclose())
            except RuntimeError:
                # 이벤트 루프가 없는 경우 - 동기적으로 정리 시도
                try:
                    asyncio.run(self._http_client.aclose())
                except:
                    # 정리 실패시 무시
                    pass