"""
Agent configuration loader
"""
from typing import Dict, Any, Optional, List
from maru_lang.configs.base import DefaultConfigLoader
from maru_lang.pluggable.models import AgentConfig
from maru_lang.enums.configs import ConfigType


class AgentConfigLoader(DefaultConfigLoader[AgentConfig]):
    """
    Loader for agent configurations

    Note: Agent configs are USER-ONLY (no base configs)
    - Builtin agents: Python in pluggable/agents/builtin, YAML in maru_app/agents/builtin
    - Custom agents: Both Python and YAML in maru_app/agents
    """

    def __init__(self):
        super().__init__(ConfigType.AGENTS)
        # Files to exclude from agent config loading
        self.exclude_files = {'build_selector.yaml', 'README.md'}

    def load_all(self) -> Dict[str, AgentConfig]:
        """Load configurations from user directory ONLY (no base configs)"""
        import logging
        logger = logging.getLogger(__name__)

        self.configs = {}
        self._base_configs = {}

        # Load ONLY user configs (no base)
        logger.info(f"Loading {self.config_type} configurations from user directory...")
        user_count = self._load_from_directory(self.user_dir, is_user=True)
        logger.info(f"Loaded {len(self.configs)} {self.config_type} configs (user: {user_count})")

        return self.configs

    def _load_file(self, file_path, is_user: bool = False) -> bool:
        """Override to skip excluded files"""
        # Skip excluded files
        if file_path.name in self.exclude_files:
            return False

        # Call parent's _load_file
        return super()._load_file(file_path, is_user)

    def parse_config(self, data: Dict[str, Any], source_path: str, is_user: bool) -> Optional[AgentConfig]:
        """Parse agent configuration data"""
        try:
            return AgentConfig(
                name=data['name'],
                description=data.get('description', ''),
                type=data.get('type', ''),
                enabled=data.get('enabled', True),
                version=data.get('version', '1.0.0'),
                priority=data.get('priority', 1),
                selection_criteria=data.get('selection_criteria'),
                target_llm_config=data.get('target_llm_config'),
                prompts=data.get('prompts'),
                config=data.get('config'),
                tools=data.get('tools', {}),
                permissions=data.get('permissions', []),
                implementation=data.get('implementation'),
                mcp_config=data.get('mcp_config'),
                source_path=source_path,
                is_override=is_user,
                examples=data.get('examples', [])
            )
        except KeyError as e:
            import sys
            error_msg = f"Error parsing agent config from {source_path}: missing required field {e}"
            print(f"\n❌ CRITICAL ERROR: {error_msg}", file=sys.stderr)
            print(f"Required fields: name, type, enabled", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            import sys
            error_msg = f"Error parsing agent config from {source_path}: {e}"
            print(f"\n❌ ERROR: {error_msg}", file=sys.stderr)
            return None

    def get_config_name(self, config: AgentConfig) -> str:
        """Get the name of an agent configuration"""
        return config.name

    def validate_config(self, data: Dict[str, Any]) -> bool:
        """Validate agent configuration data"""
        required_fields = ['name']
        return all(field in data for field in required_fields)

    def get_enabled_agents(self) -> Dict[str, AgentConfig]:
        """Get only enabled agent configurations"""
        return {name: config for name, config in self.configs.items() if config.enabled}

    def get_agents_by_type(self, agent_type: str) -> Dict[str, AgentConfig]:
        """Get agents by type (builtin, mcp_client, etc.)"""
        return {name: config for name, config in self.configs.items()
                if config.type == agent_type and config.enabled}

    def get_agents_for_permissions(self, user_permissions: List[str]) -> Dict[str, AgentConfig]:
        """Get agents available for user based on permissions"""
        available = {}
        for name, config in self.configs.items():
            if not config.enabled:
                continue

            # If agent has no permission requirements, it's available to all
            if not config.permissions:
                available[name] = config
            # Check if user has any of the required permissions
            elif any(perm in user_permissions for perm in config.permissions):
                available[name] = config

        return available

    def get_agents_by_priority(self) -> List[AgentConfig]:
        """Get enabled agents sorted by priority (highest first)"""
        enabled = self.get_enabled_agents()
        return sorted(enabled.values(), key=lambda x: x.priority, reverse=True)
