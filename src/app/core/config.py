import re
from typing import Optional
from urllib.parse import quote_plus, urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


_TELEGRAM_WEBHOOK_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
_TELEGRAM_WEBHOOK_SECRET_PLACEHOLDER_PREFIXES = ("your-", "replace-", "change-me", "example-")
_TELEGRAM_BOT_TOKEN_PATTERN = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")


def is_valid_telegram_bot_token(value: Optional[str]) -> bool:
    """Reject placeholders and malformed Bot API tokens before a network request."""
    token = (value or "").strip()
    return bool(
        _TELEGRAM_BOT_TOKEN_PATTERN.fullmatch(token)
        and not token.lower().startswith(_TELEGRAM_WEBHOOK_SECRET_PLACEHOLDER_PREFIXES)
    )


class Settings(BaseSettings):
    """
    Application Settings dynamically loaded from environment variables and .env file.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # General App Config
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str = "default-secret-key-please-change-in-production"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CURRENT_ACADEMIC_YEAR: str = "2026-2027"
    CORS_ALLOWED_ORIGINS: str = ""

    # LLM Settings
    LLM_PROVIDER: str = "openai"  # openai | ollama
    DEFAULT_MODEL: str = "gpt-4o-mini"
    EMBEDDING_PROVIDER: str = "openai"  # openai | mock | future providers
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_VECTOR_SIZE: int = 1536
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: Optional[str] = None
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "llama3.2"
    OLLAMA_REQUEST_TIMEOUT_SECONDS: float = 120.0
    ALLOW_MOCK_PROVIDERS: bool = True

    # Database
    DATABASE_URL: Optional[str] = None
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres_password_here"
    POSTGRES_DB: str = "academic_assistant_db"
    POSTGRES_HOST: str = "127.0.0.1"
    POSTGRES_PORT: int = 5432
    POSTGRES_DOCKER_CONTAINER: Optional[str] = None
    DATABASE_CONNECT_TIMEOUT_SECONDS: float = 2.0
    SQL_ECHO: bool = False

    # Qdrant
    QDRANT_HOST: str = "127.0.0.1"
    QDRANT_PORT: int = 6333
    QDRANT_URL: Optional[str] = None
    QDRANT_COLLECTION: str = "practice_knowledge"
    QDRANT_API_KEY: Optional[str] = None

    # RAG / Practice Knowledge Base
    KNOWLEDGE_BASE_DIR: str = "knowledge_base"
    RAG_CHUNK_SIZE: int = 800
    RAG_CHUNK_OVERLAP: int = 100
    RAG_TOP_K: int = 5
    RAG_SCORE_THRESHOLD: float = 0.35

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_WEBHOOK_SECRET: Optional[str] = None
    TELEGRAM_ALLOWED_USER_IDS: str = ""
    TELEGRAM_WEBHOOK_URL: Optional[str] = None

    # Email integrations
    EMAIL_PROVIDER: str = "imap"
    EMAIL_ACCOUNT: Optional[str] = None
    EMAIL_PASSWORD: Optional[str] = None
    EMAIL_IMAP_SERVER: Optional[str] = None
    EMAIL_IMAP_PORT: int = 993
    EMAIL_IMAP_FOLDER: str = "INBOX"
    EMAIL_IMAP_USE_SSL: bool = True
    EMAIL_SMTP_SERVER: Optional[str] = None
    EMAIL_SMTP_PORT: int = 587
    EMAIL_SMTP_USE_STARTTLS: bool = True
    UNITBV_EMAIL_PROVIDER: str = "imap"
    UNITBV_EMAIL_ACCOUNT: Optional[str] = None
    UNITBV_EMAIL_PASSWORD: Optional[str] = None
    UNITBV_EMAIL_IMAP_SERVER: Optional[str] = "outlook.office365.com"
    UNITBV_EMAIL_IMAP_PORT: int = 993
    UNITBV_EMAIL_IMAP_FOLDER: str = "INBOX"
    UNITBV_EMAIL_IMAP_USE_SSL: bool = True
    UNITBV_EMAIL_SMTP_SERVER: Optional[str] = "smtp.office365.com"
    UNITBV_EMAIL_SMTP_PORT: int = 587
    UNITBV_EMAIL_SMTP_USE_STARTTLS: bool = True

    # Google Calendar
    CALENDAR_PROVIDER: str = "google"
    GOOGLE_AUTH_MODE: str = "oauth"  # oauth | service_account
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/google/callback"
    GOOGLE_TOKEN_FILE: str = "secrets/google-calendar-token.json"
    GOOGLE_SERVICE_ACCOUNT_FILE: Optional[str] = None
    GOOGLE_CALENDAR_ID: str = "primary"
    GOOGLE_CALENDAR_SCOPES: str = "https://www.googleapis.com/auth/calendar"
    GOOGLE_CALENDAR_TIMEZONE: str = "Europe/Bucharest"

    # News / RSS
    NEWS_CONFIG_FILE: str = "config/news.example.yaml"
    NEWS_MAX_RESULTS: int = 5

    # n8n
    N8N_HOST: str = "localhost"
    N8N_PORT: int = 5678
    N8N_WEBHOOK_URL: Optional[str] = None
    AUTOMATION_API_KEY: Optional[str] = None

    # Human-in-the-Loop Settings
    REQUIRE_HUMAN_APPROVAL_FOR_EMAILS: bool = True
    REQUIRE_HUMAN_APPROVAL_FOR_CALENDAR_MODS: bool = True
    DRAFT_APPROVAL_TTL_SECONDS: int = 900

    # Hardening / Observability
    EXTERNAL_RETRY_ATTEMPTS: int = 2
    EXTERNAL_REQUEST_TIMEOUT_SECONDS: float = 45.0
    AUDIT_LOG_ENABLED: bool = True
    AUDIT_LOG_STORE_REQUEST_CONTENT: bool = False
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    TELEGRAM_RATE_LIMIT_REQUESTS: int = 30
    RATE_LIMIT_MAX_TRACKED_KEYS: int = 10_000

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() in {"production", "prod"}

    @property
    def mocks_allowed(self) -> bool:
        """Mocks are a local/test aid and must never mask production integration failures."""
        return self.ALLOW_MOCK_PROVIDERS and not self.is_production

    @property
    def effective_database_url(self) -> str:
        """Use an explicit URL when supplied, otherwise build one from PostgreSQL fields."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        user = quote_plus(self.POSTGRES_USER)
        password = quote_plus(self.POSTGRES_PASSWORD)
        database = quote_plus(self.POSTGRES_DB)
        return (
            f"postgresql+asyncpg://{user}:{password}@{self.POSTGRES_HOST}:"
            f"{self.POSTGRES_PORT}/{database}"
        )

    @property
    def effective_qdrant_url(self) -> str:
        """Build a coherent Qdrant URL from QDRANT_URL or QDRANT_HOST/QDRANT_PORT."""
        return self.QDRANT_URL or f"http://{self.QDRANT_HOST}:{self.QDRANT_PORT}"

    @property
    def telegram_allowed_user_ids(self) -> set[str]:
        return {item.strip() for item in self.TELEGRAM_ALLOWED_USER_IDS.split(",") if item.strip()}

    @property
    def has_valid_telegram_bot_token(self) -> bool:
        return is_valid_telegram_bot_token(self.TELEGRAM_BOT_TOKEN)

    @property
    def has_valid_telegram_webhook_secret(self) -> bool:
        """Telegram accepts a 1-256 character token; require strong safe values here."""
        secret = (self.TELEGRAM_WEBHOOK_SECRET or "").strip()
        return bool(
            _TELEGRAM_WEBHOOK_SECRET_PATTERN.fullmatch(secret)
            and not secret.lower().startswith(_TELEGRAM_WEBHOOK_SECRET_PLACEHOLDER_PREFIXES)
        )

    @property
    def has_valid_telegram_webhook_url(self) -> bool:
        """A Bot API webhook must be a public HTTPS URL without embedded credentials."""
        try:
            parsed = urlparse((self.TELEGRAM_WEBHOOK_URL or "").strip())
        except ValueError:
            return False
        return bool(
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
        )

    @property
    def google_calendar_scopes(self) -> list[str]:
        return [scope.strip() for scope in self.GOOGLE_CALENDAR_SCOPES.split(",") if scope.strip()]

    @property
    def cors_allowed_origins(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()]

    def production_validation_errors(self) -> list[str]:
        if not self.is_production:
            return []
        errors = []
        if self.SECRET_KEY == "default-secret-key-please-change-in-production" or len(self.SECRET_KEY) < 32:
            errors.append("SECRET_KEY must be a non-default value of at least 32 characters")
        if self.ALLOW_MOCK_PROVIDERS:
            errors.append("ALLOW_MOCK_PROVIDERS must be false")
        if not self.cors_allowed_origins:
            errors.append("CORS_ALLOWED_ORIGINS must list allowed HTTPS frontend origins")
        if self.DRAFT_APPROVAL_TTL_SECONDS <= 0:
            errors.append("DRAFT_APPROVAL_TTL_SECONDS must be greater than zero")
        if self.RATE_LIMIT_WINDOW_SECONDS <= 0 or self.TELEGRAM_RATE_LIMIT_REQUESTS <= 0:
            errors.append("rate-limit window and request limit must be greater than zero")
        if self.OLLAMA_REQUEST_TIMEOUT_SECONDS <= 0:
            errors.append("OLLAMA_REQUEST_TIMEOUT_SECONDS must be greater than zero")
        if self.TELEGRAM_BOT_TOKEN:
            if not self.has_valid_telegram_bot_token:
                errors.append("TELEGRAM_BOT_TOKEN must be a valid Bot API token format")
            if not self.has_valid_telegram_webhook_secret:
                errors.append(
                    "TELEGRAM_WEBHOOK_SECRET must be a 32-256 character URL-safe value when TELEGRAM_BOT_TOKEN is configured"
                )
            if not self.telegram_allowed_user_ids:
                errors.append("TELEGRAM_ALLOWED_USER_IDS must list at least one authorized user when TELEGRAM_BOT_TOKEN is configured")
            if not self.has_valid_telegram_webhook_url:
                errors.append("TELEGRAM_WEBHOOK_URL must be a public HTTPS URL when TELEGRAM_BOT_TOKEN is configured")
        return errors


settings = Settings()
