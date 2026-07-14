"""
Application Settings — single source of truth, loaded once from the environment.
====================================================================================

WHY THIS FILE CHANGED
---------------------
Before, config lived in two shapes at once:
  1. this module exposed UPPER_CASE names (APP_NAME, MONGO_URL, ...), and
  2. half the codebase ignored it and called os.getenv(...) directly
     (rag.py, agent.py, rate_limiter.py, email_sender.py, database.py).

Two problems with that:
  - There was no ONE place that knew the whole configuration. A typo in an
    env var name failed silently at the call site, far from here.
  - Values were re-parsed on every os.getenv call, with defaults duplicated
    in many files that could (and did) drift — CHUNK_OVERLAP was 200 here
    and 128 in rag.py, RATE_LIMIT was 100 here and 50 in rate_limiter.py.

Now there is a typed `Settings` object (pydantic-settings). It:
  - validates types and required fields once, at import,
  - is cached via get_settings() so it's parsed a single time,
  - is the ONE place defaults live.

BACKWARD COMPATIBILITY
----------------------
Every UPPER_CASE name this module used to export is still exported (they now
read off the Settings object). So existing imports like
`from src.config.settings import MONGO_URL` keep working unchanged while you
migrate modules to `from src.config.settings import get_settings` one at a time.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings. Reads from environment + .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="Jojoba Economic Advisor", alias="APP_NAME")
    app_version: str = Field(default="2.0.0", alias="APP_VERSION")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    debug: bool = Field(default=False, alias="DEBUG")
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    reload: bool = Field(default=False, alias="RELOAD")

    mongo_url: str = Field(default="mongodb://127.0.0.1:27017", alias="MONGO_URL")
    mongo_url_prod: Optional[str] = Field(default=None, alias="MONGO_URL_2")
    db_name: str = Field(default="llmautomationai", alias="DB_NAME")

    secret_key: str = Field(default="change-me-to-a-long-random-string", alias="SECRET_KEY")
    algorithm: str = Field(default="HS256", alias="ALGORITHM")
    access_token_expire_minutes: int = Field(default=1440, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    api_key: Optional[str] = Field(default=None, alias="API_KEY")
    encryption_key: Optional[str] = Field(default=None, alias="ENCRYPTION_KEY")

    groq_api_key: Optional[str] = Field(default=None, alias="GROQ_API_KEY")
    groq_model: str = Field(default="openai/gpt-oss-120b", alias="GROQ_MODEL")

    data_dir: str = Field(default="data/raw", alias="DATA_DIR")
    chunk_size: int = Field(default=1024, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=128, alias="CHUNK_OVERLAP")
    max_retries: int = Field(default=3, alias="MAX_RETRIES")
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5", alias="EMBEDDING_MODEL")
    embedding_dim: int = Field(default=384, alias="EMBEDDING_DIM")
    chroma_collection: str = Field(default="my_collection", alias="CHROMA_COLLECTION")

    similarity_top_k: int = Field(default=8, alias="SIMILARITY_TOP_K")
    hybrid_enabled: bool = Field(default=True, alias="HYBRID_ENABLED")
    hybrid_alpha: float = Field(default=0.5, alias="HYBRID_ALPHA")
    rerank_enabled: bool = Field(default=True, alias="RERANK_ENABLED")
    rerank_model: str = Field(default="Xenova/ms-marco-MiniLM-L-6-v2", alias="RERANK_MODEL")
    rerank_top_n: int = Field(default=4, alias="RERANK_TOP_N")
    adaptive_top_k: bool = Field(default=True, alias="ADAPTIVE_TOP_K")
    query_rewrite_enabled: bool = Field(default=True, alias="QUERY_REWRITE_ENABLED")
    compression_enabled: bool = Field(default=True, alias="COMPRESSION_ENABLED")
    groundedness_enabled: bool = Field(default=True, alias="GROUNDEDNESS_ENABLED")
    groundedness_threshold: float = Field(default=0.35, alias="GROUNDEDNESS_THRESHOLD")

    cache_ttl: int = Field(default=3600, alias="CACHE_TTL")
    cache_max_size: int = Field(default=500, alias="CACHE_MAX_SIZE")
    semantic_cache_enabled: bool = Field(default=True, alias="SEMANTIC_CACHE_ENABLED")
    semantic_cache_threshold: float = Field(default=0.93, alias="SEMANTIC_CACHE_THRESHOLD")

    max_conversation_contexts: int = Field(default=1000, alias="MAX_CONVERSATION_CONTEXTS")
    context_ttl_hours: int = Field(default=24, alias="CONTEXT_TTL_HOURS")
    max_agent_steps: int = Field(default=10, alias="MAX_AGENT_STEPS")

    rate_limit: int = Field(default=50, alias="RATE_LIMIT")
    rate_limit_period: int = Field(default=60, alias="RATE_LIMIT_PERIOD")

    email_enabled: bool = Field(default=False, alias="EMAIL_ENABLED")
    email_provider: str = Field(default="brevo", alias="EMAIL_PROVIDER")
    smtp_host: str = Field(default="smtp.gmail.com", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: Optional[str] = Field(default=None, alias="SMTP_USER")
    smtp_password: Optional[str] = Field(default=None, alias="SMTP_PASSWORD")
    from_email: Optional[str] = Field(default=None, alias="FROM_EMAIL")
    from_name: str = Field(default="Jojoba Economic Review", alias="FROM_NAME")
    brevo_api_key: Optional[str] = Field(default=None, alias="BREVO_API_KEY")

    public_base_url: str = Field(default="http://app:8000", alias="PUBLIC_BASE_URL")
    n8n_webhook_url: Optional[str] = Field(default=None, alias="N8N_WEBHOOK_URL")
    n8n_webhook_token: Optional[str] = Field(default=None, alias="N8N_WEBHOOK_TOKEN")
    n8n_default_base_url: str = Field(default="https://app.n8n.cloud", alias="N8N_DEFAULT_BASE_URL")
    # API key untuk instance n8n default di atas — HANYA di .env BACKEND.
    # Dipakai saat user memilih mode "default" tanpa pernah melihat kredensialnya.
    n8n_api_key: Optional[str] = Field(default=None, alias="N8N_API_KEY")

    otel_enabled: bool = Field(default=False, alias="OTEL_ENABLED")
    otel_service_name: str = Field(default="jojoba-advisor", alias="OTEL_SERVICE_NAME")
    otel_exporter_otlp_endpoint: Optional[str] = Field(default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT")

    cors_origins_raw: str = Field(
        default="http://localhost:3000,http://localhost:3001,https://jojobanews.vercel.app",
        alias="CORS_ORIGINS",
    )

    @field_validator("environment")
    @classmethod
    def _normalize_env(cls, v: str) -> str:
        return v.strip().lower()

    @property
    def effective_mongo_url(self) -> str:
        """Use the production URI when ENVIRONMENT=production and it's set."""
        if self.environment == "production" and self.mongo_url_prod:
            return self.mongo_url_prod
        return self.mongo_url

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins_raw.split(",") if o.strip()]

    @property
    def encryption_secret(self) -> str:
        """The raw secret used to derive the Fernet key for user-secret encryption."""
        return self.encryption_key or self.secret_key

    def summary(self) -> dict:
        """Safe-to-log snapshot — never includes secrets."""
        return {
            "app_name": self.app_name,
            "app_version": self.app_version,
            "environment": self.environment,
            "debug": self.debug,
            "database": self.db_name,
            "llm_configured": bool(self.groq_api_key),
            "email_enabled": self.email_enabled,
            "otel_enabled": self.otel_enabled,
            "hybrid_enabled": self.hybrid_enabled,
            "rerank_enabled": self.rerank_enabled,
        }


@lru_cache
def get_settings() -> Settings:
    """Return the cached Settings singleton. Import THIS in new code.

    Cached so the .env is parsed once. In tests you can override by calling
    get_settings.cache_clear() after monkeypatching the environment.
    """
    return Settings()


# ============================================================================
# BACKWARD-COMPAT SHIM
# ----------------------------------------------------------------------------
# Old modules do `from src.config.settings import MONGO_URL`. Keep those names
# alive so nothing breaks the day you drop this file in. Migrate at your pace.
# ============================================================================
_s = get_settings()

APP_NAME = _s.app_name
APP_VERSION = _s.app_version
DEBUG = _s.debug
API_HOST = _s.api_host
API_PORT = _s.api_port
RELOAD = _s.reload
ENVIRONMENT = _s.environment

MONGO_URL = _s.effective_mongo_url
MONGO_URL_PROD = _s.mongo_url_prod
DB_NAME = _s.db_name

SECRET_KEY = _s.secret_key
API_KEY = _s.api_key
ALGORITHM = _s.algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = _s.access_token_expire_minutes

GROQ_API_KEY = _s.groq_api_key

DATA_DIR = _s.data_dir
CHUNK_SIZE = _s.chunk_size
CHUNK_OVERLAP = _s.chunk_overlap
MAX_RETRIES = _s.max_retries

RATE_LIMIT = _s.rate_limit
RATE_LIMIT_PERIOD = _s.rate_limit_period

EMAIL_ENABLED = _s.email_enabled
SMTP_HOST = _s.smtp_host
SMTP_PORT = _s.smtp_port
SMTP_USER = _s.smtp_user
SMTP_PASSWORD = _s.smtp_password

N8N_WEBHOOK_URL = _s.n8n_webhook_url

CORS_ORIGINS = _s.cors_origins
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_METHODS = ["*"]
CORS_ALLOW_HEADERS = ["*"]


def validate_settings() -> bool:
    """Kept for main.py compatibility. Warns on missing critical config."""
    import logging

    logger = logging.getLogger(__name__)
    missing = []
    if not _s.groq_api_key:
        missing.append("GROQ_API_KEY")
    if _s.email_enabled and not (_s.smtp_user or _s.brevo_api_key):
        missing.append("SMTP_USER or BREVO_API_KEY (EMAIL_ENABLED=true)")
    if missing:
        logger.warning("⚠️ Missing/blank config: %s", ", ".join(missing))
        return False
    logger.info("✓ Settings validated (environment: %s)", _s.environment)
    return True


def get_settings_summary() -> dict:
    return _s.summary()
