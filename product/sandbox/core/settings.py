"""sandbox-runner configuration, read from the environment (and `.env` in development).

Same layout as reg-memory's settings (one group per concern, ``settings.<group>``).
Every value has a safe development default.
"""

from __future__ import annotations

import os
import tempfile
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
    service_name: str = Field("sandbox-runner", validation_alias="LOG_SERVICE_NAME")

    @property
    def is_local(self) -> bool:
        return self.env in _LOCAL_ENVS


class ExecSettings(BaseSettings):
    """Limits of one ``POST /v1/exec`` call (utils/runner.py)."""

    model_config = _BASE_MODEL_CONFIG

    # Per-call temp workdirs live here (a tmpfs in compose).
    work_root: Path = Field(
        Path(tempfile.gettempdir()) / "sandbox-work", validation_alias="SANDBOX_WORK_ROOT"
    )
    default_timeout_seconds: int = Field(
        120, ge=1, validation_alias="SANDBOX_DEFAULT_TIMEOUT_SECONDS"
    )
    max_timeout_seconds: int = Field(900, ge=1, validation_alias="SANDBOX_MAX_TIMEOUT_SECONDS")
    # Address-space cap per command (RLIMIT_AS). numpy/sklearn need ~1 GB of
    # virtual address space just to import, so keep this generous.
    memory_mb: int = Field(3072, ge=64, validation_alias="SANDBOX_MEMORY_MB")
    # Captured bytes per stream; the command is killed once it prints more.
    max_output_bytes: int = Field(1024 * 1024, ge=1024, validation_alias="SANDBOX_MAX_OUTPUT_BYTES")
    # Total bytes the workdir may hold after the command (and per file: RLIMIT_FSIZE).
    max_disk_bytes: int = Field(
        256 * 1024 * 1024, ge=1024, validation_alias="SANDBOX_MAX_DISK_BYTES"
    )
    max_processes: int = Field(256, ge=8, validation_alias="SANDBOX_MAX_PROCESSES")
    # The contract's transfer caps, each way (same numbers as the agents client).
    max_files: int = Field(100, ge=1, validation_alias="SANDBOX_MAX_FILES")
    max_transfer_bytes: int = Field(20 * 1024 * 1024, validation_alias="SANDBOX_MAX_TRANSFER_BYTES")
    max_concurrent: int = Field(4, ge=1, validation_alias="SANDBOX_MAX_CONCURRENT")
    # Environment variables passed through to commands (comma-separated names):
    # how a command reaches MLflow and the model gateway. Nothing else leaks in.
    passthrough_env: str = Field(
        "MLFLOW_TRACKING_URI,MODEL_GATEWAY_URL,MODEL_GATEWAY_TOKEN",
        validation_alias="SANDBOX_PASSTHROUGH_ENV",
    )

    @property
    def passthrough_names(self) -> list[str]:
        return [n.strip() for n in self.passthrough_env.split(",") if n.strip()]


class SecuritySettings(BaseSettings):
    """The shared-secret gate on every /v1 route (core/security/client.py)."""

    model_config = _BASE_MODEL_CONFIG

    secret_header: str = Field("X-Internal-Proxy-Secret", validation_alias="SANDBOX_SECRET_HEADER")
    # Empty = open in development/test, every /v1 call refused (503) elsewhere.
    trusted_proxy_secret: SecretStr = Field(default_factory=lambda: SecretStr(""))

    @field_validator("trusted_proxy_secret", mode="before")
    @classmethod
    def _load_secret(cls, value: object) -> object:
        if isinstance(value, str) and value:
            return value
        return _resolve_file_backed_secret("TRUSTED_PROXY_SECRET") or ""


class RateLimitSettings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    ip_max_calls: int = Field(600, validation_alias="IP_RATE_LIMIT_MAX_CALLS")
    ip_window_seconds: int = Field(60, validation_alias="IP_RATE_LIMIT_WINDOW_SECONDS")
    exec_max_attempts: int = Field(120, validation_alias="EXEC_RATE_LIMIT_MAX_ATTEMPTS")
    exec_window_seconds: int = Field(60, validation_alias="EXEC_RATE_LIMIT_WINDOW_SECONDS")


class ClientSettings(BaseSettings):
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
    exec: ExecSettings = Field(default_factory=ExecSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    client: ClientSettings = Field(default_factory=ClientSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        if not self.logging.redaction_secret.get_secret_value():
            object.__setattr__(self.logging, "redaction_secret", SecretStr(os.urandom(32).hex()))
        return self


settings = Settings()
