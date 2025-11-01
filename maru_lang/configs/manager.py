"""
Unified Configuration Manager - Central management for all configurations
"""
import logging
from typing import Optional, Dict, Any
from pathlib import Path
from maru_lang.pluggable.configs import (
    LLMConfigLoader,
    AgentConfigLoader,
    LoaderConfigLoader,
    ChunkerConfigLoader,
    EmbedderConfigLoader,
    RerankerConfigLoader,
    RagConfigLoader,
)

logger = logging.getLogger(__name__)


class ConfigManager:
    """
    Central configuration manager for the entire application
    Manages LLM, Group, and Agent configurations
    """

    _instance = None

    def __new__(cls):
        """Singleton pattern to ensure single instance"""
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize configuration manager"""
        if self._initialized:
            return

        # Initialize all loaders
        self.llm_loader = LLMConfigLoader()
        self.rag_loader = RagConfigLoader()  # RAG 설정 (retriever + groups)
        self.agent_loader = AgentConfigLoader()
        self.loader_config_loader = LoaderConfigLoader()
        self.chunker_config_loader = ChunkerConfigLoader()
        self.embedder_config_loader = EmbedderConfigLoader()
        self.reranker_config_loader = RerankerConfigLoader()

        self._initialized = True
        self._loaded = False

    def load_all(self) -> Dict[str, Any]:
        """Load all configurations"""
        logger.info("Loading all configurations...")

        results = {
            'llm': self.llm_loader.load_all(),
            'rag': self.rag_loader.load_all(),
            'agent': self.agent_loader.load_all(),
            'loader': self.loader_config_loader.load_all(),
            'chunker': self.chunker_config_loader.load_all(),
            'embedder': self.embedder_config_loader.load_all(),
            'reranker': self.reranker_config_loader.load_all(),
        }

        self._loaded = True

        # Log summary
        logger.info(f"Loaded configurations:")
        logger.info(f"  - LLM: {len(results['llm'])} servers")
        logger.info(f"  - RAG: {len(self.rag_loader.all_groups)} groups")
        logger.info(f"  - Agents: {len(results['agent'])} agents")
        logger.info(f"  - Loaders: {len(results['loader'])} configs")
        logger.info(f"  - Chunkers: {len(results['chunker'])} configs")
        logger.info(f"  - Embedders: {len(results['embedder'])} configs")
        logger.info(f"  - Rerankers: {len(results['reranker'])} configs")

        return results

    def reload_all(self) -> Dict[str, Any]:
        """Reload all configurations"""
        logger.info("Reloading all configurations...")

        results = {
            'llm': self.llm_loader.reload(),
            'rag': self.rag_loader.reload(),
            'agent': self.agent_loader.reload(),
            'loader': self.loader_config_loader.reload(),
            'chunker': self.chunker_config_loader.reload(),
            'embedder': self.embedder_config_loader.reload(),
            'reranker': self.reranker_config_loader.reload(),
        }

        logger.info("All configurations reloaded")
        return results

    def validate_all(self) -> Dict[str, Any]:
        """Validate all configurations and return status"""
        status = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'details': {}
        }

        # Validate LLM configs
        llm_summary = self.llm_loader.get_summary()
        status['details']['llm'] = {
            'total': llm_summary['total'],
            'base': llm_summary['base'],
            'overrides': llm_summary['overrides']
        }

        # Validate RAG configs
        rag_summary = self.rag_loader.get_summary()
        status['details']['rag'] = {
            'total': rag_summary['total'],
            'groups': len(self.rag_loader.all_groups)
        }

        # Validate Agent configs
        agent_summary = self.agent_loader.get_summary()
        status['details']['agent'] = {
            'total': agent_summary['total'],
            'base': agent_summary['base'],
            'overrides': agent_summary['overrides'],
            'enabled': len(self.agent_loader.get_enabled_agents())
        }

        # Check for missing configs and warnings
        no_llm_warning = self.llm_loader.check_no_llm_warning()
        if no_llm_warning:
            # If there are no configs at all, it's an error
            if llm_summary['total'] == 0:
                status['errors'].append("No LLM configurations found")
                status['valid'] = False
                # Also add the detailed warning message
                status['warnings'].append(no_llm_warning)
            else:
                # If there are configs but still warnings (shouldn't happen but just in case)
                status['warnings'].append(no_llm_warning)

        if len(self.rag_loader.all_groups) == 0:
            status['warnings'].append("No RAG/group configurations found")

        if agent_summary['total'] == 0:
            status['warnings'].append("No agent configurations found")

        return status

    def ensure_loaded(self):
        """Ensure configurations are loaded"""
        if not self._loaded:
            self.load_all()

    # Convenience methods for accessing specific configurations
    def get_llm(self, name: str):
        """Get LLM configuration by name"""
        return self.llm_loader.get(name)

    def get_group(self, name: str):
        """Get group configuration by name"""
        return self.rag_loader.get_group(name)

    def get_rag_config(self):
        """Get RAG configuration (first config found)"""
        configs = self.rag_loader.get_all()
        if configs:
            # Return first config (typically rag_config.yaml)
            return next(iter(configs.values()))
        return None

    def get_agent(self, name: str):
        """Get agent configuration by name"""
        return self.agent_loader.get(name)

    def get_enabled_agents(self):
        """Get all enabled agent configurations"""
        return self.agent_loader.get_enabled_agents()

    def get_agents_by_type(self, agent_type: str):
        """Get agents by type"""
        return self.agent_loader.get_agents_by_type(agent_type)

    def get_agents_for_permissions(self, user_permissions):
        """Get agents available for user based on permissions"""
        return self.agent_loader.get_agents_for_permissions(user_permissions)

    def get_loader_config(self):
        """Get merged loader configuration"""
        return self.loader_config_loader.get_merged_config()

    def get_chunker_config(self):
        """Get merged chunker configuration"""
        return self.chunker_config_loader.get_merged_config()

    def get_embedder_config(self):
        """Get merged embedder configuration"""
        return self.embedder_config_loader.get_merged_config()

    def get_reranker_config(self):
        """Get merged reranker configuration"""
        return self.reranker_config_loader.get_merged_config()


# Global instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """Get the global configuration manager instance"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager
