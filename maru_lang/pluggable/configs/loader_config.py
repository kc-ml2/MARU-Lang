"""
Loader configuration loader
"""
from typing import Dict, Any, Optional
from maru_lang.configs.base import DefaultConfigLoader
from maru_lang.pluggable.models import LoaderConfig
from maru_lang.enums.configs import ConfigType


class LoaderConfigLoader(DefaultConfigLoader[LoaderConfig]):
    """Loader for loader (parser) configurations"""

    def __init__(self):
        super().__init__(ConfigType.LOADERS)
        # Loaders는 base config 없이 user config만 사용
        # (명시적 설정을 강제하기 위해)

    def load_all(self) -> Dict[str, LoaderConfig]:
        """Load configurations from user directory only (no base)"""
        import logging
        logger = logging.getLogger(__name__)

        self.configs = {}
        self._base_configs = {}

        # User config만 로드 (base 없음) - 특정 파일만 읽기
        logger.info(f"Loading {self.config_type} configurations from user directory...")

        # loader_config.yaml만 읽기 (사용자 정의 parser .py 파일 제외)
        config_file = self.user_dir / "loader_config.yaml"
        if config_file.exists():
            if self._load_file(config_file, is_user=True):
                logger.info(f"Loaded loader config from {config_file}")
            else:
                logger.warning(f"Failed to load loader config from {config_file}")
        else:
            logger.warning(f"Loader config file not found: {config_file}")

        logger.info(
            f"Loaded {len(self.configs)} {self.config_type} configs"
        )

        return self.configs

    def parse_config(
        self, data: Dict[str, Any], source_path: str, is_user: bool
    ) -> Optional[LoaderConfig]:
        """Parse loader configuration data"""
        try:
            return LoaderConfig(
                default_loader=data.get("default_loader", "txt"),
                default_chunker=data.get("default_chunker", "paragraph"),
                extensions=data.get("extensions", {}),
                source_path=source_path,
                is_override=is_user,
            )
        except Exception as e:
            import sys

            error_msg = f"Error parsing loader config from {source_path}: {e}"
            print(f"\n❌ ERROR: {error_msg}", file=sys.stderr)
            return None

    def get_config_name(self, config: LoaderConfig) -> str:
        """Get the name of a loader configuration"""
        # 단일 config 파일이므로 고정 이름 사용
        return "config"

    def validate_config(self, data: Dict[str, Any]) -> bool:
        """Validate loader configuration data"""
        # 필수 필드가 없으므로 기본적으로 유효
        return True

    def get_merged_config(self) -> LoaderConfig:
        """
        Get merged configuration (base + user override)

        Returns:
            Merged LoaderConfig with user overrides applied
        """
        # Base config
        base = self.configs.get("config")
        if not base:
            # Return default if no config found
            return LoaderConfig()

        return base
