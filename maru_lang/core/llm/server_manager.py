"""LLM Manager - model management and fallback chains."""
import logging
from typing import Optional

from langchain_core.language_models import BaseChatModel

from .client import LLMClient
from maru_lang.configs import get_config
from maru_lang.configs.models import LLMConfig

logger = logging.getLogger(__name__)


class LLMManager:
    """Manage configured LLM clients and provide fallback chains."""

    def __init__(self, configs: Optional[list[LLMConfig]] = None):
        """Initialize with LLM configs. If None, loads from config on initialize()."""
        self.clients: list[LLMClient] = []
        if configs is not None:
            self._init_from_configs(configs)

    def _init_from_configs(self, configs: list[LLMConfig]) -> None:
        self.clients = [
            LLMClient(config)
            for config in configs
            if config.enabled
        ]
        logger.info(f"Loaded {len(self.clients)} LLM clients")

    def initialize(self) -> None:
        """Load LLM configs from config file (lazy init)."""
        logger.info("Loading LLM configurations...")
        cfg = get_config()

        if not cfg.llms:
            logger.warning("No LLM configurations found.")
            return

        self._init_from_configs(cfg.llms)

    def get_model(self, name: Optional[str] = None) -> Optional[BaseChatModel]:
        """Return a model by name, or the first available model."""
        if name:
            client = self.get_client_by_name(name)
            return client.model if client else None
        return self.clients[0].model if self.clients else None

    def get_model_with_fallbacks(
        self,
        primary_name: Optional[str] = None,
    ) -> Optional[BaseChatModel]:
        """Return a model with fallback chain."""
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

    def list_clients(self) -> list[dict]:
        """Return metadata for all clients."""
        return [
            {
                "name": client.config.name,
                "provider": client.config.provider,
                "model": client.config.model_name,
            }
            for client in self.clients
        ]
