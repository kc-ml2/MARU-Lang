"""
System configuration loader for system_config.yaml

Loads system-wide settings including server, database, auth, email, vector_db, and external services.
"""
import logging
from pathlib import Path
from typing import Any, Dict, Literal, Optional
from dataclasses import dataclass
import yaml

logger = logging.getLogger(__name__)


@dataclass
class ServerConfig:
    """Server configuration"""
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False
    log_level: str = "info"


@dataclass
class EnvironmentConfig:
    """Environment configuration"""
    production: bool = False


@dataclass
class DatabaseConfig:
    """Database configuration"""
    type: Literal["sqlite", "postgres"] = "sqlite"
    name: str = "chatbot"
    username: Optional[str] = None
    password: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None

    def get_database_url(self) -> str:
        """Generate database URL based on type"""
        if self.type == "sqlite":
            # Project root path
            project_root = Path.cwd()
            db_path = project_root / f"{self.name}.db"
            return f"sqlite:///{db_path.absolute()}"
        elif self.type == "postgres":
            if not all([self.username, self.password, self.host, self.port, self.name]):
                raise ValueError("PostgreSQL configuration is incomplete")
            return f"postgres://{self.username}:{self.password}@{self.host}:{self.port}/{self.name}"
        else:
            raise ValueError(f"Unsupported database type: {self.type}")


@dataclass
class AuthConfig:
    """Authentication and security configuration"""
    secret_key: str = "your-secret-key-change-in-production"
    salt: str = "some-salt"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_minutes: int = 43200  # 30 days
    default_validation_code: str = "456123"


@dataclass
class SMTPConfig:
    """SMTP configuration"""
    host: Optional[str] = None
    port: int = 587
    username: Optional[str] = None
    password: Optional[str] = None


@dataclass
class EmailConfig:
    """Email service configuration"""
    smtp: SMTPConfig = None

    def __post_init__(self):
        if self.smtp is None:
            self.smtp = SMTPConfig()


@dataclass
class ChromaConfig:
    """Chroma database configuration"""
    persist_dir: str = "data/chroma/"

    def get_persist_dir_absolute(self) -> str:
        """Get absolute path for Chroma persist directory"""
        project_root = Path.cwd()
        chroma_path = project_root / self.persist_dir
        return str(chroma_path.absolute())


@dataclass
class MilvusConfig:
    """Milvus database configuration"""
    host: str = "localhost"
    port: int = 19530
    user: str = "root"
    password: str = "Milvus"


@dataclass
class VectorDBConfig:
    """Vector database configuration"""
    type: Literal["chroma", "milvus"] = "chroma"
    default_collection_name: str = "maru"
    chroma: ChromaConfig = None
    milvus: MilvusConfig = None

    def __post_init__(self):
        if self.chroma is None:
            self.chroma = ChromaConfig()
        if self.milvus is None:
            self.milvus = MilvusConfig()


@dataclass
class LLMSystemConfig:
    """LLM system configuration"""
    # Default timeout for LLM requests in seconds
    default_timeout: float = 120.0


@dataclass
class SystemConfig:
    """Complete system configuration"""
    server: ServerConfig
    environment: EnvironmentConfig
    database: DatabaseConfig
    auth: AuthConfig
    email: EmailConfig
    vector_db: VectorDBConfig
    llm: LLMSystemConfig


class SystemConfigLoader:
    """Loader for system_config.yaml with environment variable support"""

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize system config loader

        Args:
            config_path: Path to system_config.yaml (default: maru_app/system_config.yaml)
        """
        if config_path is None:
            self.config_path = Path.cwd() / "maru_app" / "system_config.yaml"
        else:
            self.config_path = config_path

        self.config: Optional[SystemConfig] = None

    def _substitute_env_vars(self, data: Any) -> Any:
        """
        Recursively substitute environment variables in data structure
        This uses the existing substitution logic from DefaultConfigLoader
        """
        import os
        import re

        if isinstance(data, dict):
            return {key: self._substitute_env_vars(value) for key, value in data.items()}
        elif isinstance(data, list):
            return [self._substitute_env_vars(item) for item in data]
        elif isinstance(data, str):
            # Pattern: ${ENV:VAR_NAME} or ${ENV:VAR_NAME:default}
            pattern = r'\$\{ENV:([A-Z0-9_]+)(?::([^}]*))?\}'

            # Check if the entire string is a single env var substitution
            full_match = re.fullmatch(pattern, data)
            if full_match:
                var_name = full_match.group(1)
                default_value = full_match.group(2)

                env_value = os.getenv(var_name)

                if env_value is not None:
                    # Type conversion for boolean values
                    if env_value.lower() in ('true', 'false'):
                        return env_value.lower() == 'true'
                    # Try to convert to int
                    try:
                        return int(env_value)
                    except ValueError:
                        return env_value
                elif default_value is not None:
                    # Type conversion for default values
                    if default_value.lower() in ('true', 'false'):
                        return default_value.lower() == 'true'
                    try:
                        return int(default_value)
                    except ValueError:
                        return default_value if default_value else ""
                else:
                    return ""

            # If not a full match, do string substitution (returns string only)
            def replacer(match):
                var_name = match.group(1)
                default_value = match.group(2)

                env_value = os.getenv(var_name)
                if env_value is not None:
                    return env_value
                elif default_value is not None:
                    return default_value
                else:
                    return ""

            return re.sub(pattern, replacer, data)
        else:
            return data

    def _parse_server_config(self, data: Dict[str, Any]) -> ServerConfig:
        """Parse server configuration"""
        return ServerConfig(
            host=data.get('host', '127.0.0.1'),
            port=int(data.get('port', 8000)),
            reload=bool(data.get('reload', False)),
            log_level=data.get('log_level', 'info')
        )

    def _parse_environment_config(self, data: Dict[str, Any]) -> EnvironmentConfig:
        """Parse environment configuration"""
        return EnvironmentConfig(
            production=bool(data.get('production', False))
        )

    def _parse_database_config(self, data: Dict[str, Any]) -> DatabaseConfig:
        """Parse database configuration"""
        return DatabaseConfig(
            type=data.get('type', 'sqlite'),
            name=data.get('name', 'chatbot'),
            username=data.get('username'),
            password=data.get('password'),
            host=data.get('host'),
            port=int(data['port']) if data.get('port') else None
        )

    def _parse_auth_config(self, data: Dict[str, Any]) -> AuthConfig:
        """Parse authentication configuration"""
        return AuthConfig(
            secret_key=data.get('secret_key', 'your-secret-key-change-in-production'),
            salt=data.get('salt', 'some-salt'),
            algorithm=data.get('algorithm', 'HS256'),
            access_token_expire_minutes=int(data.get('access_token_expire_minutes', 15)),
            refresh_token_expire_minutes=int(data.get('refresh_token_expire_minutes', 43200)),
            default_validation_code=data.get('default_validation_code', '456123')
        )

    def _parse_email_config(self, data: Dict[str, Any]) -> EmailConfig:
        """Parse email configuration"""
        smtp_data = data.get('smtp', {})

        return EmailConfig(
            smtp=SMTPConfig(
                host=smtp_data.get('host'),
                port=int(smtp_data.get('port', 587)),
                username=smtp_data.get('username'),
                password=smtp_data.get('password')
            )
        )

    def _parse_vector_db_config(self, data: Dict[str, Any]) -> VectorDBConfig:
        """Parse vector database configuration"""
        chroma_data = data.get('chroma', {})
        milvus_data = data.get('milvus', {})

        return VectorDBConfig(
            type=data.get('type', 'chroma'),
            default_collection_name=data.get('default_collection_name', 'maru'),
            chroma=ChromaConfig(
                persist_dir=chroma_data.get('persist_dir', 'data/chroma/')
            ),
            milvus=MilvusConfig(
                host=milvus_data.get('host', 'localhost'),
                port=int(milvus_data.get('port', 19530)),
                user=milvus_data.get('user', 'root'),
                password=milvus_data.get('password', 'Milvus')
            )
        )

    def _parse_llm_config(self, data: Dict[str, Any]) -> LLMSystemConfig:
        """Parse LLM system configuration"""
        return LLMSystemConfig(
            default_timeout=float(data.get('default_timeout', 120.0))
        )

    def load(self) -> SystemConfig:
        """Load system configuration from YAML file"""
        if not self.config_path.exists():
            # Silently return default configuration
            # (no warning needed as defaults are sufficient)
            self.config = SystemConfig(
                server=ServerConfig(),
                environment=EnvironmentConfig(),
                database=DatabaseConfig(),
                auth=AuthConfig(),
                email=EmailConfig(),
                vector_db=VectorDBConfig(),
                llm=LLMSystemConfig()
            )
            return self.config

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                raw_data = yaml.safe_load(f)

            if raw_data is None:
                raise ValueError("Empty configuration file")

            # Substitute environment variables
            data = self._substitute_env_vars(raw_data)

            # Parse each section
            self.config = SystemConfig(
                server=self._parse_server_config(data.get('server', {})),
                environment=self._parse_environment_config(data.get('environment', {})),
                database=self._parse_database_config(data.get('database', {})),
                auth=self._parse_auth_config(data.get('auth', {})),
                email=self._parse_email_config(data.get('email', {})),
                vector_db=self._parse_vector_db_config(data.get('vector_db', {})),
                llm=self._parse_llm_config(data.get('llm', {}))
            )

            logger.info(f"Loaded system configuration from {self.config_path}")
            return self.config

        except Exception as e:
            logger.error(f"Error loading system config from {self.config_path}: {e}")
            raise

    def get_config(self) -> SystemConfig:
        """Get loaded configuration (load if not already loaded)"""
        if self.config is None:
            self.load()
        return self.config


# Global instance
_system_config_loader = SystemConfigLoader()


def get_system_config() -> SystemConfig:
    """Get global system configuration"""
    return _system_config_loader.get_config()


def reload_system_config() -> SystemConfig:
    """Reload system configuration"""
    return _system_config_loader.load()
