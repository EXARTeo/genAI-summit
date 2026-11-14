"""model-gateway configuration, read from the environment (and `.env` in development).

Same layout as the backend's and reg-memory's settings (one group per concern,
``settings.<group>``); only what this service uses. Every value has a safe
development default.
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
    service_name: str = Field("model-gateway", validation_alias="LOG_SERVICE_NAME")
    # Artificial delay added to every model/chat call, to behave like a remote endpoint.
    latency_ms: int = Field(0, ge=0, le=10_000, validation_alias="MODEL_GATEWAY_LATENCY_MS")
    # Upper bound on rows per predict/screen call (a real API caps batch size).
    max_rows: int = Field(1000, ge=1, le=100_000, validation_alias="MODEL_GATEWAY_MAX_ROWS")

    @property
    def is_local(self) -> bool:
        return self.env in _LOCAL_ENVS


class MlflowSettings(BaseSettings):
    """Where the seed models live (registered models, alias ``champion``)."""

    model_config = _BASE_MODEL_CONFIG

    tracking_uri: str = Field("http://mlflow:5000", validation_alias="MLFLOW_TRACKING_URI")
    model_alias: str = Field("champion", validation_alias="MODEL_GATEWAY_MODEL_ALIAS")


class SecuritySettings(BaseSettings):
    """The bearer-token gate on every /v1 route (core/security/client.py)."""

    model_config = _BASE_MODEL_CONFIG

    # Empty = open in development/test, every /v1 call refused (503) elsewhere.
    token: SecretStr = Field(default_factory=lambda: SecretStr(""))

    @field_validator("token", mode="before")
    @classmethod
    def _load_token(cls, value: object) -> object:
        if isinstance(value, str) and value:
            return value
        return _resolve_file_backed_secret("MODEL_GATEWAY_TOKEN") or ""


class RateLimitSettings(BaseSettings):
    """Every limit, env-tunable. See core/security/rate_limit.py for the keys."""

    model_config = _BASE_MODEL_CONFIG

    # Global budget per client IP across every endpoint.
    ip_max_calls: int = Field(600, validation_alias="IP_RATE_LIMIT_MAX_CALLS")
    ip_window_seconds: int = Field(60, validation_alias="IP_RATE_LIMIT_WINDOW_SECONDS")
    # Per bearer token on every model/chat call: the endpoint's published limit.
    token_max_calls: int = Field(5, ge=1, validation_alias="MODEL_GATEWAY_RATE_LIMIT_RPS")
    token_window_seconds: int = Field(
        1, ge=1, validation_alias="MODEL_GATEWAY_RATE_LIMIT_WINDOW_SECONDS"
    )


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
    mlflow: MlflowSettings = Field(default_factory=MlflowSettings)
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
