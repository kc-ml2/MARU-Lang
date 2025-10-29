"""
Chunker configuration loader
"""
from typing import Dict, Any, Optional
from maru_lang.configs.base import DefaultConfigLoader
from maru_lang.pluggable.models import ChunkerConfig
from maru_lang.enums.configs import ConfigType


class ChunkerConfigLoader(DefaultConfigLoader[ChunkerConfig]):
    """Loader for chunker configurations"""

    def __init__(self):
        super().__init__(ConfigType.CHUNKERS)
        # Chunkers는 base config 없이 user config만 사용
        # (명시적 설정을 강제하기 위해)

    def load_all(self) -> Dict[str, ChunkerConfig]:
        """Load configurations from user directory only (no base)"""
        import logging
        logger = logging.getLogger(__name__)

        self.configs = {}
        self._base_configs = {}

        # User config만 로드 (base 없음)
        logger.info(f"Loading {self.config_type} configurations from user directory...")
        user_count = self._load_from_directory(self.user_dir, is_user=True)
        logger.info(
            f"Loaded {len(self.configs)} {self.config_type} configs (user: {user_count})"
        )

        return self.configs

    def parse_config(
        self, data: Dict[str, Any], source_path: str, is_user: bool
    ) -> Optional[ChunkerConfig]:
        """Parse chunker configuration data"""
        try:
            return ChunkerConfig(
                chunkers=data.get("chunkers", {}),
                source_path=source_path,
                is_override=is_user,
            )
        except Exception as e:
            import sys

            error_msg = f"Error parsing chunker config from {source_path}: {e}"
            print(f"\n❌ ERROR: {error_msg}", file=sys.stderr)
            return None

    def get_config_name(self, config: ChunkerConfig) -> str:
        """Get the name of a chunker configuration"""
        # 단일 config 파일이므로 고정 이름 사용
        return "config"

    def validate_config(self, data: Dict[str, Any]) -> bool:
        """Validate chunker configuration data"""
        # 필수 필드가 없으므로 기본적으로 유효
        return True

    def get_merged_config(self) -> ChunkerConfig:
        """
        Get merged configuration (base + user override)

        Returns:
            Merged ChunkerConfig with user overrides applied
        """
        # Base config
        base = self.configs.get("config")
        if not base:
            # Return default if no config found
            return ChunkerConfig()

        return base
