from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    app_name: str = "FlowForge"
    public_app_url: str = "http://localhost:3000"
    public_api_url: str = "http://localhost:8000"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://flowforge:flowforge@localhost:5432/flowforge"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: SecretStr = SecretStr("change-me-in-production-at-least-32-bytes")
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    email_token_ttl_hours: int = 24
    invitation_ttl_days: int = 7
    cookie_secure: bool = False

    # Fernet key for the credential vault. Generate with:
    # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    credentials_key: SecretStr = SecretStr("")

    llm_provider: Literal["openrouter", "fake"] = "openrouter"
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_chat_model: str = "openai/gpt-4o-mini"
    openrouter_fallback_models: list[str] = Field(default_factory=list)
    openrouter_embedding_model: str = "openai/text-embedding-3-small"
    embedding_dimensions: int = 1536
    llm_timeout_seconds: float = 60.0

    # Outbound HTTP from workflow nodes. Private addresses are blocked to prevent SSRF;
    # enable only for local development and tests.
    allow_private_network_requests: bool = False
    http_node_max_response_bytes: int = 2 * 1024 * 1024

    run_job_timeout_seconds: int = 900
    # Runs execute in the worker, so it serves its own Prometheus endpoint (0 disables it).
    worker_metrics_port: int = 9100
    default_step_timeout_seconds: float = 30.0
    max_step_timeout_seconds: float = 300.0

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_use_tls: bool = False
    email_from: str = "FlowForge <no-reply@flowforge.local>"

    google_token_url: str = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL
    google_sheets_api_url: str = "https://sheets.googleapis.com/v4"
    telegram_api_url: str = "https://api.telegram.org"

    rate_limit_enabled: bool = True

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider == "fake" or bool(self.openrouter_api_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
