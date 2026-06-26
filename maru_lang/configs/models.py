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
    weight: int = 1  # 가입 시 사용자 배정 목표 비율 (least-filled 밸런싱)
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
    # Sized to a typical working session (kept refreshable via the 30-day
    # refresh token), rather than forcing a refresh round-trip every 15 min.
    access_token_expire_minutes: int = 120
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
        # Fail closed on malformed input: an address must have exactly one "@".
        # `email.split("@")[-1]` alone would let "attacker@evil.com@kct.co.kr"
        # pass by matching only the trailing label, so reject anything that is
        # not a clean local@domain pair before comparing.
        parts = (email or "").strip().split("@")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return False
        domain = parts[1].lower()
        return domain in [d.lower() for d in self.allowed_domains]


@dataclass
class SMTPConfig:
    host: Optional[str] = None
    port: int = 587
    username: Optional[str] = None
    password: Optional[str] = None


@dataclass
class LangfuseConfig:
    """Langfuse observability (LLM tracing) configuration.

    Disabled by default. When enabled with valid keys, a CallbackHandler is
    attached to each chat-graph run so every LLM node (route/intent/generate/
    summarize/...) is traced automatically.
    """
    enabled: bool = False
    public_key: Optional[str] = None
    secret_key: Optional[str] = None
    host: str = "https://cloud.langfuse.com"

    @property
    def is_active(self) -> bool:
        """True only when turned on AND both keys are present."""
        return bool(self.enabled and self.public_key and self.secret_key)


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
    # Directory for email message overrides, resolved relative to cwd (the project
    # root that holds maru_app/). Each "<name>.txt" (otp/invitation/notification)
    # uses its first line as the subject and the rest as the body; missing files
    # fall back to the built-in defaults in dependencies/email_templates.py.
    # `maru install` seeds "*.txt.example" copies here.
    email_template_dir: str = "maru_app/templates/email"
    langfuse: LangfuseConfig = field(default_factory=LangfuseConfig)
    vector_db_url: str = "chroma://data/chroma/maru"
    storage_dir: str = "data/storage"
    # LangGraph checkpointer. If None, derived from database_url
    # (sqlite -> sibling "<db>.checkpoints" file; postgres -> same DB, separate tables).
    checkpoint_db_url: Optional[str] = None

    # LLMs
    llms: list[LLMConfig] = field(default_factory=list)

    # Embedder
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: Optional[str] = None  # query/retrieval device; None=auto (GPU if avail)
    # Document (ingest) embedding device, used by the ARQ worker / ingest pipeline.
    # None -> falls back to embedding_device. Split these to keep a single GPU copy,
    # e.g. embedding_device=cpu (query) + ingest_embedding_device=cuda (worker bulk).
    ingest_embedding_device: Optional[str] = None

    # Ingest task queue (ARQ). When enabled, /ingest/upload enqueues the embedding
    # job to a separate ARQ worker process instead of running it in-process via
    # FastAPI BackgroundTasks. Disabled -> identical to the in-process behavior.
    # Enabling requires redis_url (validated in __post_init__).
    task_queue_enabled: bool = False
    redis_url: Optional[str] = None  # e.g. "redis://localhost:6379"

    # KorDoc MCP parser. Enabled by default — KorDoc-supported formats are parsed
    # via the KorDoc MCP server (run locally as `npx -y kordoc mcp`, needs Node)
    # instead of the LangChain loaders. Formats only KorDoc can read
    # (hwp/hwpx/hwpml) always go to KorDoc; formats both can read
    # (pdf/docx/xls/xlsx) are split by kordoc_mcp_ratio — deterministically per
    # document — so the two parsers' quality can be A/B compared on the same
    # corpus. Set false on deployments without Node/npx.
    kordoc_mcp_enabled: bool = True
    kordoc_mcp_command: str = "npx"
    kordoc_mcp_args: list = field(default_factory=lambda: ["-y", "kordoc", "mcp"])
    # Share of dual-support docs routed to KorDoc. Default 0.0: KorDoc handles
    # only what LangChain can't (hwp/hwpx/hwpml) — KorDoc's PDF path needs the
    # extra pdfjs-dist npm package, so out of the box PDFs stay on LangChain.
    # Raise (e.g. 0.5) to A/B-compare parser quality on the same corpus.
    kordoc_mcp_ratio: float = 0.0
    kordoc_mcp_timeout: float = 120.0  # seconds; bounds the per-document MCP call

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
    # Drop reranked docs scoring below this (cross_encoder only). Raw scores are
    # model-dependent, so it's opt-in; None keeps every reranked doc.
    reranker_min_score: Optional[float] = None

    _DEFAULT_SECRET_KEY: str = field(default="your-secret-key-change-in-production", init=False, repr=False)

    def __post_init__(self):
        if self.production and self.auth.secret_key == self._DEFAULT_SECRET_KEY:
            logger.warning(
                "SECURITY: production=True but auth.secret_key is the default value. "
                "Set a strong secret_key in maru_config.yaml before deploying."
            )
        if self.task_queue_enabled and not self.redis_url:
            # Fail fast rather than silently falling back to in-process ingest —
            # otherwise the queue looks "on" but jobs never reach a worker.
            raise ValueError(
                "task_queue_enabled=true requires redis_url (e.g. redis://localhost:6379). "
                "Set redis_url in maru_config.yaml, or set task_queue_enabled=false."
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
                    weight=int(llm_data.get("weight", 1)),
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
            access_token_expire_minutes=int(auth_data.get("access_token_expire_minutes", 120)),
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

        # Langfuse (observability)
        lf_data = data.get("langfuse", {}) or {}
        langfuse = LangfuseConfig(
            enabled=bool(lf_data.get("enabled", False)),
            public_key=lf_data.get("public_key"),
            secret_key=lf_data.get("secret_key"),
            host=lf_data.get("host", LangfuseConfig.host),
        )

        return cls(
            server=server,
            production=bool(data.get("production", False)),
            database_url=data.get("database_url", cls.database_url),
            auth=auth,
            smtp=smtp,
            email_template_dir=data.get("email_template_dir", cls.email_template_dir),
            langfuse=langfuse,
            vector_db_url=data.get("vector_db_url", cls.vector_db_url),
            storage_dir=data.get("storage_dir", cls.storage_dir),
            checkpoint_db_url=data.get("checkpoint_db_url"),
            llms=llms,
            embedding_model=data.get("embedding_model", cls.embedding_model),
            embedding_device=data.get("embedding_device"),
            ingest_embedding_device=data.get("ingest_embedding_device"),
            task_queue_enabled=bool(data.get("task_queue_enabled", False)),
            redis_url=data.get("redis_url"),
            kordoc_mcp_enabled=bool(data.get("kordoc_mcp_enabled", cls.kordoc_mcp_enabled)),
            kordoc_mcp_command=data.get("kordoc_mcp_command", cls.kordoc_mcp_command),
            kordoc_mcp_args=data.get("kordoc_mcp_args") or ["-y", "kordoc", "mcp"],
            kordoc_mcp_ratio=float(data.get("kordoc_mcp_ratio", cls.kordoc_mcp_ratio)),
            kordoc_mcp_timeout=float(data.get("kordoc_mcp_timeout", cls.kordoc_mcp_timeout)),
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
            reranker_min_score=data.get("reranker_min_score"),
        )

    # --- Convenience helpers ---

    @property
    def queue_enabled(self) -> bool:
        """True when the ingest task queue is active (flag on + redis_url set)."""
        return bool(self.task_queue_enabled and self.redis_url)

    def resolve_ingest_embedding_device(self) -> Optional[str]:
        """Device for document (ingest) embedding; falls back to embedding_device."""
        return (
            self.ingest_embedding_device
            if self.ingest_embedding_device is not None
            else self.embedding_device
        )

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
