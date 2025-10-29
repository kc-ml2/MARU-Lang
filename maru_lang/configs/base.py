"""
Base configuration loader for YAML-based configs with environment variable support
"""
import os
import re
import yaml
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Any, TypeVar, Generic, Union
from dataclasses import dataclass
from maru_lang.enums.configs import ConfigType

logger = logging.getLogger(__name__)

T = TypeVar('T')


class DefaultConfigLoader(ABC, Generic[T]):
    """Abstract base class for configuration loaders with environment variable support"""

    def __init__(
        self,
        config_type: Union[ConfigType, str],
    ):
        """
        Initialize configuration loader

        Args:
            config_type: Type of configuration
        """
        # Handle both enum and string inputs for backward compatibility
        if isinstance(config_type, ConfigType):
            self.config_type = config_type.value
        else:
            self.config_type = config_type

        # Set directories
        # base_dir: 패키지 내부의 기본 설정
        self.base_dir = Path(__file__).parent / self.config_type
        # user_dir: 사용자가 maru_app 디렉토리에 만든 설정
        self.user_dir = Path.cwd() / "maru_app" / self.config_type

        # Storage for loaded configs
        self.configs: Dict[str, T] = {}
        # Track base configs for override detection
        self._base_configs: Dict[str, T] = {}

        # Ensure directories exist
        self._ensure_directories()

    def _ensure_directories(self):
        """Create necessary directories if they don't exist"""
        for directory in [self.base_dir, self.user_dir]:
            if not directory.exists():
                directory.mkdir(parents=True, exist_ok=True)
                logger.debug(f"Created directory: {directory}")

    def _substitute_env_vars(self, data: Any, file_path: str = "") -> Any:
        """
        Recursively substitute environment variables in data structure

        Supports formats:
        - ${ENV:VAR_NAME} - required env var (error if not found)
        - ${ENV:VAR_NAME:default} - optional env var with default

        Args:
            data: Data structure (dict, list, str, etc.)
            file_path: Source file path for error messages

        Returns:
            Data with environment variables substituted
        """
        if isinstance(data, dict):
            return {key: self._substitute_env_vars(value, file_path) for key, value in data.items()}
        elif isinstance(data, list):
            return [self._substitute_env_vars(item, file_path) for item in data]
        elif isinstance(data, str):
            return self._replace_env_in_string(data, file_path)
        else:
            return data

    def _replace_env_in_string(self, value: str, file_path: str = "") -> str:
        """
        Replace environment variable references in a string

        Formats:
        - ${ENV:VAR_NAME} - required
        - ${ENV:VAR_NAME:default_value} - with default
        """
        # Pattern: ${ENV:VAR_NAME} or ${ENV:VAR_NAME:default}
        pattern = r'\$\{ENV:([A-Z0-9_]+)(?::([^}]*))?\}'

        def replacer(match):
            var_name = match.group(1)
            default_value = match.group(2)

            env_value = os.getenv(var_name)

            if env_value is not None:
                return env_value
            elif default_value is not None:
                logger.debug(f"Using default value for {var_name}")
                return default_value
            else:
                raise ValueError(
                    f"Environment variable '{var_name}' not found in {file_path}\n"
                    f"Please set it in your .env file or environment."
                )

        return re.sub(pattern, replacer, value)

    @abstractmethod
    def parse_config(self, data: Dict[str, Any], source_path: str, is_user: bool) -> Optional[T]:
        """
        Parse configuration data into specific config object

        Args:
            data: Raw YAML data
            source_path: Path to the source file
            is_user: Whether this is a user config

        Returns:
            Parsed configuration object or None if invalid
        """
        pass

    @abstractmethod
    def get_config_name(self, config: T) -> str:
        """Get the name/identifier of a configuration"""
        pass

    @abstractmethod
    def validate_config(self, data: Dict[str, Any]) -> bool:
        """Validate configuration data"""
        pass

    def load_all(self) -> Dict[str, T]:
        """Load all configurations (base + user)"""
        self.configs = {}
        self._base_configs = {}

        # Load base configs first
        logger.info(f"Loading {self.config_type} configurations...")
        base_count = self._load_from_directory(self.base_dir, is_user=False)
        # Store base configs for override detection
        self._base_configs = self.configs.copy()

        # Load user configs (may override base)
        user_count = self._load_from_directory(self.user_dir, is_user=True)
        logger.info(
            f"Loaded {len(self.configs)} {self.config_type} configs "
            f"(base: {base_count}, user: {user_count})"
        )

        return self.configs

    def _load_from_directory(self, directory: Path, is_user: bool = False) -> int:
        """Load all YAML configs from a directory"""
        if not directory.exists():
            logger.debug(f"Directory does not exist: {directory}")
            return 0

        count = 0
        # Recursively find all .yaml files
        for yaml_file in directory.rglob("*.yaml"):
            if self._load_file(yaml_file, is_user):
                count += 1

        return count

    def _load_file(self, file_path: Path, is_user: bool = False) -> bool:
        """Load a single YAML file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            if data is None:
                logger.warning(f"Empty config file: {file_path}")
                return False

            # Substitute environment variables
            try:
                data = self._substitute_env_vars(data, str(file_path))
            except ValueError as e:
                logger.error(f"Environment variable error: {e}")
                raise

            # Validate config structure
            if not self.validate_config(data):
                logger.warning(f"Invalid config structure: {file_path}")
                return False

            # Parse config
            config = self.parse_config(data, str(file_path), is_user)
            if config is None:
                return False

            # Store config
            config_name = self.get_config_name(config)
            self.configs[config_name] = config

            logger.debug(f"Loaded config: {config_name} from {file_path}")
            return True

        except yaml.YAMLError as e:
            logger.error(f"YAML parsing error in {file_path}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error loading config from {file_path}: {e}")
            return False

    def get(self, name: str) -> Optional[T]:
        """Get a configuration by name"""
        return self.configs.get(name)

    def get_all(self) -> Dict[str, T]:
        """Get all configurations"""
        return self.configs.copy()

    def reload(self) -> Dict[str, T]:
        """Reload all configurations"""
        return self.load_all()

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of loaded configurations"""
        base_count = len(self._base_configs)
        user_count = len(self.configs) - base_count
        override_count = sum(
            1 for name in self.configs
            if name in self._base_configs and self.configs[name] != self._base_configs[name]
        )

        return {
            'total': len(self.configs),
            'base': base_count,
            'user': user_count,
            'overrides': override_count
        }
