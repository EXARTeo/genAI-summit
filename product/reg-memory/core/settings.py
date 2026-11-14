"""reg-memory configuration, read from the environment (and `.env` in development).

Same layout as the backend's settings (one group per concern, ``settings.<group>``);
only what this service uses. Every value has a safe development default.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE_MODEL_CONFIG = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
    case_sensitive=False,
)

_LOCAL_ENVS = frozenset({"development", "test"})

SERVICE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = SERVICE_ROOT / "engine" / "catalog" / "sources.yaml"


def _resolve_file_backed_secret(*env_names: str) -> str | None:
    """Resolve a secret from ``<NAME>_FILE`` (Docker secret) or ``<NAME>`` itself."""
    for name in env_names:
        file_path = os.getenv(f"{name}_FILE")
        if file_path:
            try:
                value = Path(file_path).read_text().strip()
            except OSError as exc:
                raise RuntimeError(
                    f"{name}_FILE points to {file_path!r} but could not be read: {exc}"
                ) from exc
            if value:
                return value
        raw = os.getenv(name)
        if raw and raw.strip():
            return raw.strip()
    return None


class AppSettings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    env: str = Field("development", validation_alias=AliasChoices("APP_ENV", "ENV"))
    version: str = Field("dev", validation_alias=AliasChoices("APP_VERSION", "IMAGE_TAG"))
    service_name: str = Field("reg-memory", validation_alias="LOG_SERVICE_NAME")
    # Start a full ingest at startup when the store has no manifests yet.
    bootstrap_on_start: bool = Field(False, validation_alias="REG_MEMORY_BOOTSTRAP_ON_START")

    @property
    def is_local(self) -> bool:
        return self.env in _LOCAL_ENVS


class StoreSettings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    # The one data volume: raw, text, diffs, manifests, runs, catalog snapshots.
    data_dir: Path = Field(Path("./data"), validation_alias="REG_MEMORY_DATA_DIR")
    catalog_path: Path = Field(DEFAULT_CATALOG, validation_alias="REG_MEMORY_CATALOG")


class FetchSettings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    user_agent: str = Field("reg-memory/0.1", validation_alias="REG_MEMORY_USER_AGENT")
    timeout_seconds: float = Field(60.0, validation_alias="REG_MEMORY_HTTP_TIMEOUT_SECONDS")
    retries: int = Field(3, ge=0, le=10, validation_alias="REG_MEMORY_HTTP_RETRIES")
    max_bytes: int = Field(50 * 1024 * 1024, validation_alias="REG_MEMORY_MAX_BYTES")
    concurrency: int = Field(8, ge=1, le=32, validation_alias="REG_MEMORY_CONCURRENCY")
    # Minimum gap between two requests to the same host (EC sites 429 faster clients).
    host_interval_seconds: float = Field(
        3.0, ge=0, validation_alias="REG_MEMORY_HOST_INTERVAL_SECONDS"
    )
    # Optional fallback for pages that answer plain HTTP with a bot challenge.
    firecrawl_api_key: SecretStr = Field(
        default_factory=lambda: SecretStr(""), validation_alias="FIRECRAWL_API_KEY"
    )
    firecrawl_url: str = Field("https://api.firecrawl.dev", validation_alias="FIRECRAWL_API_URL")


class SecuritySettings(BaseSettings):
    """The internal-secret gate on every /v1 route (core/security/client.py)."""

    model_config = _BASE_MODEL_CONFIG

    internal_secret_header: str = Field(
        "X-Internal-Secret", validation_alias="REG_MEMORY_INTERNAL_SECRET_HEADER"
    )
    # Empty = open in development/test, every /v1 call refused (503) elsewhere.
    internal_secret: SecretStr = Field(default_factory=lambda: SecretStr(""))

    @field_validator("internal_secret", mode="before")
    @classmethod
    def _load_secret(cls, value: object) -> object:
        if isinstance(value, str) and value:
            return value
        return _resolve_file_backed_secret("REG_MEMORY_INTERNAL_SECRET") or ""


class RateLimitSettings(BaseSettings):
    """Every limit, env-tunable. See core/security/rate_limit.py for the keys."""

    model_config = _BASE_MODEL_CONFIG

    # Global budget per client IP across every endpoint.
    ip_max_calls: int = Field(600, validation_alias="IP_RATE_LIMIT_MAX_CALLS")
    ip_window_seconds: int = Field(60, validation_alias="IP_RATE_LIMIT_WINDOW_SECONDS")
    # Starting an ingest downloads from public EU sites — the tightest bucket.
    ingest_max_attempts: int = Field(10, validation_alias="INGEST_RATE_LIMIT_MAX_ATTEMPTS")
    ingest_window_seconds: int = Field(60, validation_alias="INGEST_RATE_LIMIT_WINDOW_SECONDS")
    # Reads: sources, documents, texts, run status.
    read_max_attempts: int = Field(240, validation_alias="READ_RATE_LIMIT_MAX_ATTEMPTS")
    read_window_seconds: int = Field(60, validation_alias="READ_RATE_LIMIT_WINDOW_SECONDS")


class ClientSettings(BaseSettings):
    """How the service sees its caller's IP."""

    model_config = _BASE_MODEL_CONFIG

    trust_forwarded_for: bool = Field(False, validation_alias="TRUST_FORWARDED_FOR")


class LoggingSettings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    level: str = Field("INFO", validation_alias="LOG_LEVEL")
    format: str = Field("console", validation_alias="LOG_FORMAT")
    timezone: str = Field("UTC", validation_alias=AliasChoices("LOG_TIMEZONE", "TZ"))
    redaction_secret: SecretStr = Field(default_factory=lambda: SecretStr(""))

    @field_validator("level", mode="after")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @field_validator("format", mode="after")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("redaction_secret", mode="before")
    @classmethod
    def _load_redaction_secret(cls, value: object) -> object:
        if isinstance(value, SecretStr) and value.get_secret_value():
            return value
        if isinstance(value, str) and value:
            return value
        return _resolve_file_backed_secret("LOG_REDACTION_SECRET") or ""


class Settings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    app: AppSettings = Field(default_factory=AppSettings)
    store: StoreSettings = Field(default_factory=StoreSettings)
    fetch: FetchSettings = Field(default_factory=FetchSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    client: ClientSettings = Field(default_factory=ClientSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        if not self.logging.redaction_secret.get_secret_value():
            # IDs in logs are HMAC'd; without a configured secret use a per-boot
            # random one (log correlation then holds only within one process).
            object.__setattr__(self.logging, "redaction_secret", SecretStr(os.urandom(32).hex()))
        return self


settings = Settings()
