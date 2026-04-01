"""LLM Client - LangChain BaseChatModel 팩토리 및 관리"""
from __future__ import annotations

from typing import Any, Optional, Union

from langchain_core.language_models import BaseChatModel

from maru_lang.pluggable.models import LLMConfig


def create_chat_model(config: LLMConfig) -> BaseChatModel:
    """LLMConfig의 provider에 따라 적절한 LangChain ChatModel 생성

    Supported providers:
        - openai: ChatOpenAI (OpenAI, vLLM, 기타 OpenAI 호환 서버)
        - anthropic: ChatAnthropic
        - google: ChatGoogleGenerativeAI
        - ollama: ChatOllama
        - 기타: ChatOpenAI (OpenAI 호환 fallback)
    """
    model_kwargs = {**config.config}

    if config.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        kwargs: dict[str, Any] = {
            "model": config.model_name,
            "api_key": config.api_key,
        }
        if "temperature" in model_kwargs:
            kwargs["temperature"] = model_kwargs.pop("temperature")
        if "max_tokens" in model_kwargs:
            kwargs["max_tokens"] = model_kwargs.pop("max_tokens")
        else:
            kwargs["max_tokens"] = 4096
        if config.timeout:
            kwargs["timeout"] = config.timeout
        if model_kwargs:
            kwargs["model_kwargs"] = model_kwargs
        return ChatAnthropic(**kwargs)

    elif config.provider == "google":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError:
            raise ImportError("pip install langchain-google-genai")
        kwargs = {
            "model": config.model_name,
            "google_api_key": config.api_key,
        }
        if "temperature" in model_kwargs:
            kwargs["temperature"] = model_kwargs.pop("temperature")
        if "max_tokens" in model_kwargs:
            kwargs["max_output_tokens"] = model_kwargs.pop("max_tokens")
        return ChatGoogleGenerativeAI(**kwargs)

    elif config.provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError:
            raise ImportError("pip install langchain-ollama")
        kwargs = {
            "model": config.model_name,
        }
        if config.base_url:
            kwargs["base_url"] = config.base_url
        if "temperature" in model_kwargs:
            kwargs["temperature"] = model_kwargs.pop("temperature")
        return ChatOllama(**kwargs)

    else:
        # openai + 기타 OpenAI 호환 프로바이더 (xai, mistral, local 등)
        from langchain_openai import ChatOpenAI
        kwargs = {
            "model": config.model_name,
            "api_key": config.api_key,
        }
        if config.base_url:
            kwargs["base_url"] = config.base_url
        if "temperature" in model_kwargs:
            kwargs["temperature"] = model_kwargs.pop("temperature")
        if "max_tokens" in model_kwargs:
            kwargs["max_tokens"] = model_kwargs.pop("max_tokens")
        if config.timeout:
            kwargs["timeout"] = config.timeout
        if model_kwargs:
            kwargs["model_kwargs"] = model_kwargs
        return ChatOpenAI(**kwargs)


class LLMClient:
    """LLMConfig + BaseChatModel 홀더.

    Attributes:
        config: LLM 설정
        model: LangChain ChatModel 인스턴스
    """

    def __init__(self, config: Union[LLMConfig, dict]):
        if isinstance(config, dict):
            self.config = LLMConfig(**config)
        else:
            self.config = config

        self.model: BaseChatModel = create_chat_model(self.config)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LLMClient):
            return NotImplemented
        return self.config.name == other.config.name

    def __hash__(self) -> int:
        return hash(self.config.name)

    def __repr__(self) -> str:
        return f"LLMClient(name={self.config.name!r}, provider={self.config.provider!r}, model={self.config.model_name!r})"
