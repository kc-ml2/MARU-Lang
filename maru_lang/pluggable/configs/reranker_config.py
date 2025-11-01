"""
Reranker Configuration Loader
"""
import logging
from typing import Dict, Any, Optional
from maru_lang.enums.configs import ConfigType
from maru_lang.pluggable.models import RerankerConfig
from maru_lang.configs.base import DefaultConfigLoader

logger = logging.getLogger(__name__)


class RerankerConfigLoader(DefaultConfigLoader[RerankerConfig]):
    """Loader for reranker configurations"""

    def __init__(self):
        super().__init__(ConfigType.RERANKERS)

    def load_all(self) -> Dict[str, RerankerConfig]:
        """Load configurations from user directory only (no base)"""
        self.configs = {}
        self._base_configs = {}

        # User config만 로드 (base 없음) - 특정 파일만 읽기
        logger.info(f"Loading {self.config_type} configurations from user directory...")

        # reranker_config.yaml만 읽기 (llm_reranker.yaml 등 agent 설정 제외)
        config_file = self.user_dir / "reranker_config.yaml"
        if config_file.exists():
            if self._load_file(config_file, is_user=True):
                logger.info(f"Loaded reranker config from {config_file}")
            else:
                logger.warning(f"Failed to load reranker config from {config_file}")
        else:
            logger.warning(f"Reranker config file not found: {config_file}")

        logger.info(
            f"Loaded {len(self.configs)} {self.config_type} configs"
        )

        return self.configs

    def parse_config(
        self, data: Dict[str, Any], source_path: str, is_user: bool
    ) -> Optional[RerankerConfig]:
        """Parse reranker configuration data"""
        try:
            # 'models' 필드는 하위 호환성을 위해 무시 (deprecated)
            return RerankerConfig(
                enabled=data.get("enabled", True),
                method=data.get("method", "model"),
                default_model=data.get("default_model", "BAAI/bge-reranker-v2-m3"),
                agent_name=data.get("agent_name"),
                top_k=data.get("top_k"),
                source_path=source_path,
                is_override=is_user,
            )
        except Exception as e:
            import sys

            error_msg = f"Error parsing reranker config from {source_path}: {e}"
            print(f"\n❌ ERROR: {error_msg}", file=sys.stderr)
            return None

    def get_config_name(self, config: RerankerConfig) -> str:
        """Get the name of a reranker configuration"""
        # 단일 config 파일이므로 고정 이름 사용
        return "config"

    def validate_config(self, data: Dict[str, Any]) -> bool:
        """Validate reranker configuration data"""
        # 필수 필드가 없으므로 기본적으로 유효
        if not isinstance(data, dict):
            logger.error(f"Reranker config data is not a dict: {type(data)}")
            return False
        return True

    def get_merged_config(self) -> RerankerConfig:
        """
        Get merged configuration (base + user override)

        Returns:
            Merged RerankerConfig with user overrides applied
        """
        # Base config
        base = self.configs.get("config")
        if not base:
            # Return default if no config found
            return RerankerConfig()

        return base
