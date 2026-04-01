"""Unified Configuration Manager"""
import logging
from typing import Optional, Dict, Any
from maru_lang.pluggable.configs import (
    LLMConfigLoader,
    AgentConfigLoader,
    EmbedderConfigLoader,
    RerankerConfigLoader,
    RagConfigLoader,
)

logger = logging.getLogger(__name__)


class ConfigManager:
    """Central configuration manager (singleton)"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.llm_loader = LLMConfigLoader()
        self.rag_loader = RagConfigLoader()
        self.agent_loader = AgentConfigLoader()
        self.embedder_config_loader = EmbedderConfigLoader()
        self.reranker_config_loader = RerankerConfigLoader()

        self._initialized = True
        self._loaded = False

    def load_all(self) -> Dict[str, Any]:
        results = {
            'llm': self.llm_loader.load_all(),
            'rag': self.rag_loader.load_all(),
            'agent': self.agent_loader.load_all(),
            'embedder': self.embedder_config_loader.load_all(),
            'reranker': self.reranker_config_loader.load_all(),
        }
        self._loaded = True

        logger.info(f"Loaded: "
                     f"{len(results['llm'])} LLMs, "
                     f"{len(self.rag_loader.all_groups)} RAG groups, "
                     f"{len(results['agent'])} agents")
        return results

    def reload_all(self) -> Dict[str, Any]:
        results = {
            'llm': self.llm_loader.reload(),
            'rag': self.rag_loader.reload(),
            'agent': self.agent_loader.reload(),
            'embedder': self.embedder_config_loader.reload(),
            'reranker': self.reranker_config_loader.reload(),
        }
        logger.info("All configurations reloaded")
        return results

    def validate_all(self) -> Dict[str, Any]:
        status = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'details': {},
        }

        llm_summary = self.llm_loader.get_summary()
        status['details']['llm'] = {
            'total': llm_summary['total'],
            'base': llm_summary['base'],
            'overrides': llm_summary['overrides'],
        }

        rag_summary = self.rag_loader.get_summary()
        status['details']['rag'] = {
            'total': rag_summary['total'],
            'groups': len(self.rag_loader.all_groups),
        }

        agent_summary = self.agent_loader.get_summary()
        status['details']['agent'] = {
            'total': agent_summary['total'],
            'base': agent_summary['base'],
            'overrides': agent_summary['overrides'],
            'enabled': len(self.agent_loader.get_enabled_agents()),
        }

        no_llm_warning = self.llm_loader.check_no_llm_warning()
        if no_llm_warning:
            status['warnings'].append(no_llm_warning)
            if llm_summary['total'] == 0:
                status['warnings'].append(
                    "No LLM configurations found - chat will not work until configured"
                )

        if len(self.rag_loader.all_groups) == 0:
            status['warnings'].append("No RAG/group configurations found")

        if agent_summary['total'] == 0:
            status['warnings'].append("No agent configurations found")

        return status

    def ensure_loaded(self):
        if not self._loaded:
            self.load_all()

    # ─── Convenience accessors ────────────────────────────────

    def get_llm(self, name: str):
        return self.llm_loader.get(name)

    def get_group(self, name: str):
        return self.rag_loader.get_group(name)

    def get_rag_config(self):
        configs = self.rag_loader.get_all()
        if configs:
            return next(iter(configs.values()))
        raise Exception("No RAG configuration found")

    def get_agent(self, name: str):
        return self.agent_loader.get(name)

    def get_enabled_agents(self):
        return self.agent_loader.get_enabled_agents()

    def get_agents_by_type(self, agent_type: str):
        return self.agent_loader.get_agents_by_type(agent_type)

    def get_agents_for_permissions(self, user_permissions):
        return self.agent_loader.get_agents_for_permissions(user_permissions)

    def get_embedder_config(self):
        return self.embedder_config_loader.get_merged_config()

    def get_reranker_config(self):
        return self.reranker_config_loader.get_merged_config()


_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager
