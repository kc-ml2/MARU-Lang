"""
LLM configuration loader
"""
from typing import Dict, Any, Optional, List
from pathlib import Path
from maru_lang.configs.base import DefaultConfigLoader
from maru_lang.pluggable.models import LLMConfig
from maru_lang.enums.configs import ConfigType
import logging

logger = logging.getLogger(__name__)


class LLMConfigLoader(DefaultConfigLoader[LLMConfig]):
    """Loader for LLM server configurations"""

    def __init__(self):
        super().__init__(ConfigType.LLMS)
        self.sample_warnings = []  # Track sample files without yaml counterparts

    def parse_config(self, data: Dict[str, Any], source_path: str, is_user: bool) -> Optional[LLMConfig]:
        """Parse LLM configuration data"""
        try:
            return LLMConfig(
                name=data['name'],
                url=data['url'],
                model_name=data.get('model_name', data.get('model', '')),
                description=data.get('description', ''),
                api_key=data.get('api_key'),
                timeout=data.get('timeout', 30.0),
                enabled=data.get('enabled', True),
                max_retries=data.get('max_retries', 3),
                health_check_endpoint=data.get(
                    'health_check_endpoint', '/health'),
                headers=data.get('headers', {}),
                config=data.get('config', {}),
                health_check=data.get('health_check', {}),
                cost_tracking=data.get('cost_tracking', {}),
                limits=data.get('limits', {}),
                retry=data.get('retry', {}),
                log_level=data.get('log_level', 'INFO'),
                source_path=source_path,
                is_override=is_user
            )
        except KeyError as e:
            import logging
            logging.error(f"Missing required field in LLM config: {e}")
            return None

    def get_config_name(self, config: LLMConfig) -> str:
        """Get the name of an LLM configuration"""
        return config.name

    def validate_config(self, data: Dict[str, Any]) -> bool:
        """Validate LLM configuration data"""
        required_fields = ['name', 'url']
        return all(field in data for field in required_fields)

    def get_enabled_configs(self) -> List[LLMConfig]:
        """Get only enabled LLM configurations"""
        return [config for config in self.configs.values() if config.enabled]

    def get_active_configs(self, check_health: bool = False) -> List[LLMConfig]:
        """
        Get active LLM configurations

        Args:
            check_health: If True, perform health check (requires async)

        Returns:
            List of active configurations
        """
        # For now, return enabled configs
        # Health check would require async implementation
        return self.get_enabled_configs()

    def get_by_model(self, model_name: str) -> Optional[LLMConfig]:
        """Get configuration by model name"""
        for config in self.configs.values():
            if config.model_name == model_name:
                return config
        return None

    def load_all(self) -> Dict[str, LLMConfig]:
        """Override to check for sample files"""
        # First check for sample files
        self._check_sample_files()

        # Then load normally
        return super().load_all()

    def _check_sample_files(self):
        """Check for .sample files without corresponding .yaml files"""
        self.sample_warnings = []

        # Check user directory for .sample files
        if self.user_dir.exists():
            sample_files = list(self.user_dir.glob("*.yaml.sample")) + list(self.user_dir.glob("*.yml.sample"))

            for sample_file in sample_files:
                # Get the base name without .sample
                base_name = sample_file.stem  # This removes .sample
                if base_name.endswith('.yaml'):
                    base_name = base_name[:-5]
                elif base_name.endswith('.yml'):
                    base_name = base_name[:-4]

                # Check if corresponding yaml file exists
                yaml_path = sample_file.parent / f"{base_name}.yaml"
                yml_path = sample_file.parent / f"{base_name}.yml"

                if not yaml_path.exists() and not yml_path.exists():
                    self.sample_warnings.append({
                        'sample_file': sample_file.name,
                        'expected_file': f"{base_name}.yaml",
                        'base_name': base_name
                    })

        # Print warnings if any
        if self.sample_warnings:
            logger.info("📝 LLM Configuration Templates Available:")
            logger.info("  To use LLM features, create your configuration files:")
            logger.info("")
            for warning in self.sample_warnings:
                logger.info(f"  1. Copy template: cp llms/{warning['sample_file']} llms/{warning['expected_file']}")
                logger.info(f"  2. Edit llms/{warning['expected_file']} and configure your API settings")
                logger.info("")
            logger.info("  Note: You can delete unused .sample files after creating your configurations.")

    def check_no_llm_warning(self) -> Optional[str]:
        """Check if no LLM configurations exist and return warning message"""
        all_configs = list(self.configs.values())

        # Include sample warnings in the message
        warning_msgs = []

        if not all_configs and not self.sample_warnings:
            # No configs and no templates
            warning_msgs.append("⚠️  No LLM configurations found. Please add LLM server configurations in your project directory.")
        elif not all_configs and self.sample_warnings:
            # No configs but templates exist
            warning_msgs.append("📝 No active LLM configurations.")
            warning_msgs.append("   Sample templates are available. To activate LLM features:")
            for warning in self.sample_warnings:
                warning_msgs.append(f"   • cp llms/{warning['sample_file']} llms/{warning['expected_file']} (then edit API settings)")

        if warning_msgs:
            return "\n".join(warning_msgs)

        return None
