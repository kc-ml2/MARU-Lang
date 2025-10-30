"""
Embedder configuration loader
"""
from typing import Dict, Any, Optional
from maru_lang.configs.base import DefaultConfigLoader
from maru_lang.pluggable.models import EmbedderConfig
from maru_lang.enums.configs import ConfigType


class EmbedderConfigLoader(DefaultConfigLoader[EmbedderConfig]):
    """Loader for embedder configurations"""

    def __init__(self):
        super().__init__(ConfigType.EMBEDDERS)
        # Embedders는 base config 없이 user config만 사용
        # (명시적 설정을 강제하기 위해)

    def load_all(self) -> Dict[str, EmbedderConfig]:
        """Load configurations from user directory only (no base)"""
        import logging
        logger = logging.getLogger(__name__)

        self.configs = {}
        self._base_configs = {}

        # User config만 로드 (base 없음) - 특정 파일만 읽기
        logger.info(f"Loading {self.config_type} configurations from user directory...")

        # embedder_config.yaml만 읽기
        config_file = self.user_dir / "embedder_config.yaml"
        if config_file.exists():
            if self._load_file(config_file, is_user=True):
                logger.info(f"Loaded embedder config from {config_file}")
            else:
                logger.warning(f"Failed to load embedder config from {config_file}")
        else:
            logger.warning(f"Embedder config file not found: {config_file}")

        logger.info(
            f"Loaded {len(self.configs)} {self.config_type} configs"
        )

        return self.configs

    def parse_config(
        self, data: Dict[str, Any], source_path: str, is_user: bool
    ) -> Optional[EmbedderConfig]:
        """Parse embedder configuration data"""
        try:
            # 'models' 필드는 하위 호환성을 위해 무시 (deprecated)
            return EmbedderConfig(
                default_model=data.get("default_model"),
                device=data.get("device"),
                source_path=source_path,
                is_override=is_user,
            )
        except Exception as e:
            import sys

            error_msg = f"Error parsing embedder config from {source_path}: {e}"
            print(f"\n❌ ERROR: {error_msg}", file=sys.stderr)
            return None

    def get_config_name(self, config: EmbedderConfig) -> str:
        """Get the name of an embedder configuration"""
        # 단일 config 파일이므로 고정 이름 사용
        return "config"

    def validate_config(self, data: Dict[str, Any]) -> bool:
        """Validate embedder configuration data"""
        # 필수 필드가 없으므로 기본적으로 유효
        return True

    def get_merged_config(self) -> EmbedderConfig:
        """
        Get merged configuration (base + user override)

        Returns:
            Merged EmbedderConfig with user overrides applied
        """
        # Base config
        base = self.configs.get("config")
        if not base:
            # Return default if no config found
            return EmbedderConfig()

        return base
