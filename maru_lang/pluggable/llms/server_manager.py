"""LLM Manager - LangChain 모델 관리 및 fallback 체인 제공"""
import logging
from typing import List, Optional

from langchain_core.language_models import BaseChatModel

from .client import LLMClient
from maru_lang.configs.manager import get_config_manager

logger = logging.getLogger(__name__)


class LLMManager:
    """Manage configured LLM clients and provide fallback chains."""

    def __init__(self):
        self.config_manager = get_config_manager()
        self.clients: List[LLMClient] = []

    def initialize(self) -> None:
        """Load LLM configurations and create clients."""
        logger.info("Loading LLM configurations...")

        self.config_manager.ensure_loaded()
        llm_configs = list(self.config_manager.llm_loader.get_all().values())

        if not llm_configs:
            logger.warning("No LLM configurations found.")
            return

        self.clients = [
            LLMClient(config)
            for config in llm_configs
            if config.enabled
        ]
        logger.info(f"Loaded {len(self.clients)} LLM clients")

    def get_model(self, name: Optional[str] = None) -> Optional[BaseChatModel]:
        """이름으로 모델 반환. 이름 없으면 첫 번째 모델 반환."""
        if name:
            client = self.get_client_by_name(name)
            return client.model if client else None
        return self.clients[0].model if self.clients else None

    def get_model_with_fallbacks(
        self,
        primary_name: Optional[str] = None,
    ) -> Optional[BaseChatModel]:
        """fallback 체인이 적용된 모델 반환.

        primary가 실패하면 나머지 모델들이 순서대로 시도됨.
        LangChain의 with_fallbacks() 사용.
        """
        if not self.clients:
            return None

        models = [c.model for c in self.clients]

        if primary_name:
            primary_client = self.get_client_by_name(primary_name)
            if primary_client:
                others = [c.model for c in self.clients if c.config.name != primary_name]
                if others:
                    return primary_client.model.with_fallbacks(others)
                return primary_client.model

        # primary 지정 없으면 첫 번째가 primary, 나머지가 fallback
        if len(models) == 1:
            return models[0]
        return models[0].with_fallbacks(models[1:])

    def get_client(self) -> Optional[LLMClient]:
        """Return the first available client."""
        return self.clients[0] if self.clients else None

    def get_client_by_name(self, name: str) -> Optional[LLMClient]:
        """Return a client by name."""
        for client in self.clients:
            if client.config.name == name:
                return client
        return None

    def get_client_by_model(self, model_name: str) -> Optional[LLMClient]:
        """Return a client by model name."""
        for client in self.clients:
            if client.config.model_name == model_name:
                return client
        return None

    def get_client_by_provider(self, provider: str) -> Optional[LLMClient]:
        """Return a client by provider."""
        for client in self.clients:
            if client.config.provider == provider:
                return client
        return None

    def list_clients(self) -> List[dict]:
        """Return metadata for all clients."""
        return [
            {
                "name": client.config.name,
                "provider": client.config.provider,
                "model": client.config.model_name,
            }
            for client in self.clients
        ]

    def reload(self) -> None:
        """Reload configurations and reinitialize clients."""
        logger.info("Reloading LLM configurations...")
        self.clients = []
        self.config_manager.reload_all()
        self.initialize()
