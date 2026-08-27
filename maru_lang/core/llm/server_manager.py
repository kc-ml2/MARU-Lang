"""LLM Manager - configured model management."""
import logging

from langchain_core.language_models import BaseChatModel

from .client import LLMClient
from maru_lang.configs import get_config
from maru_lang.configs.models import LLMConfig

logger = logging.getLogger(__name__)


class LLMManager:
    """Manage configured LLM clients."""

    def __init__(self, configs: list[LLMConfig] | None = None):
        """Initialize the first enabled LLM, or load config lazily when omitted."""
        self.client: LLMClient | None = None
        if configs is not None:
            self._init_from_configs(configs)

    def _init_from_configs(self, configs: list[LLMConfig]) -> None:
        config = next((config for config in configs if config.enabled), None)
        self.client = LLMClient(config) if config is not None else None
        if self.client is not None:
            logger.info("Loaded process-wide LLM client: %s", self.client.config.name)

    def initialize(self) -> None:
        """Load LLM configs from config file (lazy init)."""
        logger.info("Loading LLM configurations...")
        cfg = get_config()

        if not cfg.llms:
            logger.warning("No LLM configurations found.")
            return

        self._init_from_configs(cfg.llms)

    def get_model(self) -> BaseChatModel | None:
        """Return the process-wide model."""
        return self.client.model if self.client is not None else None

    def get_client(self) -> LLMClient | None:
        """Return the process-wide client."""
        return self.client

    def list_clients(self) -> list[dict]:
        """Return metadata for the process-wide client."""
        if self.client is None:
            return []
        return [{
            "name": self.client.config.name,
            "provider": self.client.config.provider,
            "model": self.client.config.model_name,
        }]
