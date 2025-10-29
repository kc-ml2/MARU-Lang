"""
RAG configuration loader
"""
from pathlib import Path
from typing import Dict, Any, Optional, List
from maru_lang.configs.base import DefaultConfigLoader
from maru_lang.pluggable.models import RagConfig, GroupRagConfig
from maru_lang.enums.configs import ConfigType


class RagConfigLoader(DefaultConfigLoader[RagConfig]):
    """Loader for RAG configurations"""

    def __init__(self):
        super().__init__(ConfigType.RAGS)
        # Override directories - rag_config.yaml is in maru_app root
        self.base_dir = Path(__file__).parent / "rags"  # Base config location (비어있음)
        self.user_dir = Path.cwd() / "maru_app"  # User config in maru_app root
        # Flattened view of all groups
        self.all_groups: Dict[str, GroupRagConfig] = {}

    def parse_config(self, data: Dict[str, Any], source_path: str, is_user: bool) -> Optional[RagConfig]:
        """Parse RAG configuration data"""
        try:
            # Use RagConfig.from_dict for parsing
            rag_config = RagConfig.from_dict(data, source_path, is_user)

            # Store groups in flattened view
            for group_name, group_config in rag_config.groups.items():
                self.all_groups[group_name] = group_config

            return rag_config
        except Exception as e:
            import logging
            logging.error(f"Failed to parse RAG config: {e}")
            return None

    def get_config_name(self, config: RagConfig) -> str:
        """Get the name of a RAG configuration"""
        # Use filename without extension as name
        return Path(config.source_path).stem

    def validate_config(self, data: Dict[str, Any]) -> bool:
        """Validate RAG configuration data"""
        # RAG config can be more flexible
        return isinstance(data, dict)

    def get_group(self, name: str) -> Optional[GroupRagConfig]:
        """Get a specific group configuration"""
        return self.all_groups.get(name)

    def reload(self) -> Dict[str, RagConfig]:
        """Reload all configurations"""
        self.all_groups = {}  # Clear flattened groups
        return super().reload()
