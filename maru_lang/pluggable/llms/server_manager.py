import logging
from typing import List, Optional
from .client import LLMClient
from maru_lang.configs.manager import get_config_manager

logger = logging.getLogger(__name__)


class LLMManager:
    """Manage configured LLM clients."""

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

        # Create clients for enabled configurations only
        self.clients = [
            LLMClient(config)
            for config in llm_configs
            if config.enabled
        ]
        logger.info(f"Loaded {len(self.clients)} LLM clients")

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
                "model": client.config.model_name
            }
            for client in self.clients
        ]

    def reload(self) -> None:
        """Reload configurations and reinitialize clients."""
        logger.info("Reloading LLM configurations...")
        self.clients = []
        self.config_manager.reload_all()
        self.initialize()
