"""Configuration data models - single unified config."""
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# --- LLM ---

@dataclass
class LLMConfig:
    """LLM provider configuration."""
    name: str = ""
    provider: str = ""
    model_name: str = ""
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)
    timeout: Optional[float] = None

    def __post_init__(self):
        if self.api_key and self.api_key.startswith("${") and self.api_key.endswith("}"):
            env_var = self.api_key[2:-1]
            self.api_key = os.getenv(env_var)


# --- Infrastructure ---

@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False
    log_level: str = "info"


@dataclass
class AuthConfig:
    secret_key: Optional[str] = None  # Required for production
    salt: Optional[str] = None  # Required for production
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_minutes: int = 43200
    default_validation_code: str = "456123"
    allowed_domains: list = field(default_factory=list)

    def __post_init__(self):
        if self.secret_key is None:
            self.secret_key = os.getenv("SECRET_KEY", "")
        if self.salt is None:
            self.salt = os.getenv("SALT", "")

    def is_domain_allowed(self, email: str) -> bool:
        if not self.allowed_domains:
            return True
        domain = email.split("@")[-1].lower()
        return domain in [d.lower() for d in self.allowed_domains]


@dataclass
class SMTPConfig:
    host: Optional[str] = None
    port: int = 587
    username: Optional[str] = None
    password: Optional[str] = None


# --- Unified Config ---

@dataclass
class MaruConfig:
    """Unified MARU configuration - single source of truth.

    All fields have sensible defaults. Config file overrides if present.
    """
    # Infrastructure
    server: ServerConfig = field(default_factory=ServerConfig)
    production: bool = False
    database_url: str = "sqlite:///chatbot.db"
    auth: AuthConfig = field(default_factory=AuthConfig)
    smtp: SMTPConfig = field(default_factory=SMTPConfig)
    vector_db_url: str = "chroma://data/chroma/maru"
    storage_dir: str = "data/storage"
    # LangGraph checkpointer. If None, derived from database_url
    # (sqlite -> sibling "<db>.checkpoints" file; postgres -> same DB, separate tables).
    checkpoint_db_url: Optional[str] = None

    # LLMs
    llms: list[LLMConfig] = field(default_factory=list)

    # Embedder
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: Optional[str] = None

    # Retriever
    retriever_top_k: int = 5
    retriever_search_method: str = "vector"  # "vector" or "hybrid"

    # Memory
    memory_recent_turns: int = 3  # prior session turns loaded into context

    # System prompt
    system_prompt: str = ""

    # RAG evaluate
    evaluate_method: str = "rule"  # "rule" or "llm"

    # Reranker
    reranker_enabled: bool = False
    reranker_type: str = "cross_encoder"  # "cross_encoder" or "llm"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"  # cross_encoder model
    reranker_llm: Optional[str] = None  # llm name (from llms list) for llm reranker
    reranker_top_k: Optional[int] = 5
    reranker_device: Optional[str] = None

    _DEFAULT_SECRET_KEY: str = field(default="your-secret-key-change-in-production", init=False, repr=False)

    def __post_init__(self):
        if self.production and self.auth.secret_key == self._DEFAULT_SECRET_KEY:
            logger.warning(
                "SECURITY: production=True but auth.secret_key is the default value. "
                "Set a strong secret_key in maru_config.yaml before deploying."
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MaruConfig":
        """Parse from YAML dict. Unknown keys are ignored."""
        # LLMs
        llms = []
        for llm_data in (data.get("llms") or []):
            if isinstance(llm_data, dict) and "name" in llm_data and "provider" in llm_data:
                llms.append(LLMConfig(
                    name=llm_data["name"],
                    provider=llm_data["provider"],
                    model_name=llm_data.get("model_name", llm_data.get("model", "")),
                    api_key=llm_data.get("api_key"),
                    base_url=llm_data.get("base_url"),
                    enabled=llm_data.get("enabled", True),
                    config=llm_data.get("config", {}),
                    timeout=llm_data.get("timeout"),
                ))

        # Server
        server_data = data.get("server", {})
        server = ServerConfig(
            host=server_data.get("host", "127.0.0.1"),
            port=int(server_data.get("port", 8000)),
            reload=bool(server_data.get("reload", False)),
            log_level=server_data.get("log_level", "info"),
        )

        # Auth
        auth_data = data.get("auth", {})
        auth = AuthConfig(
            secret_key=auth_data.get("secret_key", AuthConfig.secret_key),
            salt=auth_data.get("salt", AuthConfig.salt),
            algorithm=auth_data.get("algorithm", AuthConfig.algorithm),
            access_token_expire_minutes=int(auth_data.get("access_token_expire_minutes", 15)),
            refresh_token_expire_minutes=int(auth_data.get("refresh_token_expire_minutes", 43200)),
            default_validation_code=auth_data.get("default_validation_code", "456123"),
            allowed_domains=auth_data.get("allowed_domains", []),
        )

        # SMTP
        smtp_data = data.get("smtp", {})
        smtp = SMTPConfig(
            host=smtp_data.get("host"),
            port=int(smtp_data.get("port", 587)),
            username=smtp_data.get("username"),
            password=smtp_data.get("password"),
        )

        return cls(
            server=server,
            production=bool(data.get("production", False)),
            database_url=data.get("database_url", cls.database_url),
            auth=auth,
            smtp=smtp,
            vector_db_url=data.get("vector_db_url", cls.vector_db_url),
            storage_dir=data.get("storage_dir", cls.storage_dir),
            checkpoint_db_url=data.get("checkpoint_db_url"),
            llms=llms,
            embedding_model=data.get("embedding_model", cls.embedding_model),
            embedding_device=data.get("embedding_device"),
            retriever_top_k=data.get("retriever_top_k", cls.retriever_top_k),
            retriever_search_method=data.get("retriever_search_method", cls.retriever_search_method),
            memory_recent_turns=data.get("memory_recent_turns", cls.memory_recent_turns),
            evaluate_method=data.get("evaluate_method", cls.evaluate_method),
            system_prompt=data.get("system_prompt", cls.system_prompt),
            reranker_enabled=data.get("reranker_enabled", cls.reranker_enabled),
            reranker_type=data.get("reranker_type", cls.reranker_type),
            reranker_model=data.get("reranker_model", cls.reranker_model),
            reranker_llm=data.get("reranker_llm"),
            reranker_top_k=data.get("reranker_top_k", cls.reranker_top_k),
            reranker_device=data.get("reranker_device"),
        )

    # --- Convenience helpers ---

    def get_database_url_absolute(self) -> str:
        """Resolve relative sqlite path to absolute."""
        if self.database_url.startswith("sqlite:///") and not Path(self.database_url[10:]).is_absolute():
            db_path = Path.cwd() / self.database_url[10:]
            return f"sqlite:///{db_path.absolute()}"
        return self.database_url

    def resolve_checkpoint_target(self) -> tuple[str, str]:
        """Resolve the LangGraph checkpointer target.

        Returns:
            (scheme, target) where scheme is "sqlite" or "postgres".
            - sqlite: target is an absolute filesystem path (no URL scheme).
            - postgres: target is a libpq/psycopg connection URI.

        Resolution order:
            1. Explicit `checkpoint_db_url` if set.
            2. Otherwise derived from `database_url`:
               - sqlite -> a sibling "<db>.checkpoints" file (separate file to
                 avoid single-writer lock contention with the relational DB).
               - postgres -> the same database URL (separate checkpoint tables).
        """
        source = self.checkpoint_db_url or self.database_url
        source_abs = source
        if source.startswith("sqlite:///"):
            # Reuse absolute-path resolution logic for relative sqlite paths.
            raw = source[10:]
            if not Path(raw).is_absolute():
                raw = str((Path.cwd() / raw).absolute())
            source_abs = f"sqlite:///{raw}"

        if source_abs.startswith("sqlite"):
            # Strip scheme -> filesystem path. AsyncSqliteSaver wants a path.
            path = source_abs[len("sqlite:///"):] if source_abs.startswith("sqlite:///") else source_abs.split("://", 1)[-1]
            if path in (":memory:", ""):
                return "sqlite", ":memory:"
            if self.checkpoint_db_url is None:
                # Derive a sibling file so the saver never shares the relational DB file.
                p = Path(path)
                path = str(p.with_suffix(p.suffix + ".checkpoints") if p.suffix else p.with_name(p.name + ".checkpoints"))
            return "sqlite", path

        # postgres / postgresql -> normalize scheme for psycopg.
        uri = source_abs
        if uri.startswith("postgres://"):
            uri = "postgresql://" + uri[len("postgres://"):]
        return "postgres", uri

    def parse_vector_db_url(self) -> tuple[str, str, str]:
        """Parse vector_db_url into (scheme, path, name).

        Examples:
            chroma://data/chroma/maru → ("chroma", "data/chroma", "maru")
            lance://data/lance/maru   → ("lance", "data/lance", "maru")
            milvus://root:pass@localhost:19530/maru → ("milvus", "root:pass@localhost:19530", "maru")
        """
        scheme, rest = self.vector_db_url.split("://", 1)
        parts = rest.rsplit("/", 1)
        if len(parts) == 2:
            return scheme, parts[0], parts[1]
        return scheme, "", parts[0]

    def get_vector_db_persist_dir_absolute(self) -> str:
        """Get absolute persist dir for file-based VectorDBs (chroma, lance)."""
        _, path, _ = self.parse_vector_db_url()
        p = Path(path)
        if not p.is_absolute():
            p = Path.cwd() / p
        return str(p.absolute())
