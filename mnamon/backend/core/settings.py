"""Backend configuration, read from the environment (and `.env` in development).

Only what this product uses: no login, no signing keys, no proxy secrets.
Every value has a safe development default except ``DATABASE_URL``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated
from urllib.parse import quote, urlsplit

import httpx
from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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


def _split_csv(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, list | tuple):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    if str(raw).strip().startswith("["):  # a JSON list is accepted too
        return _split_csv(json.loads(str(raw)))
    return tuple(part.strip() for part in str(raw).split(",") if part.strip())


def _is_public_https_origin(origin: str) -> bool:
    """``https://host[:port]`` on a host that is not loopback."""
    parsed = urlsplit(origin.strip())
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and bool(host)
        and host not in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}  # noqa: S104
    )


class AppSettings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    env: str = Field("development", validation_alias=AliasChoices("APP_ENV", "ENV"))
    version: str = Field("dev", validation_alias=AliasChoices("APP_VERSION", "IMAGE_TAG"))
    service_name: str = Field("backend", validation_alias="LOG_SERVICE_NAME")


class DatabaseSettings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    url: SecretStr = Field(..., validation_alias="DATABASE_URL")
    echo: bool = Field(False, validation_alias="DATABASE_ECHO")
    pool_pre_ping: bool = Field(True, validation_alias="DATABASE_POOL_PRE_PING")
    pool_recycle: int = Field(1800, validation_alias="DATABASE_POOL_RECYCLE")
    pool_size: int = Field(5, validation_alias="DATABASE_POOL_SIZE")
    max_overflow: int = Field(20, validation_alias="DATABASE_MAX_OVERFLOW")
    # Run `alembic upgrade head` before serving. Turn off only to get a broken
    # container up long enough to run alembic by hand.
    run_migrations_on_startup: bool = Field(True, validation_alias="RUN_MIGRATIONS_ON_STARTUP")

    @field_validator("url", mode="before")
    @classmethod
    def _inject_password(cls, value: object) -> object:
        """Splice ``DATABASE_PASSWORD(_FILE)`` into a password-less DATABASE_URL."""
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(raw, str) or "://" not in raw:
            return value
        password = _resolve_file_backed_secret("DATABASE_PASSWORD")
        if not password:
            return raw
        scheme, sep, rest = raw.partition("://")
        authority, slash, tail = rest.partition("/")
        if "@" not in authority:
            return raw
        userinfo, at, hostport = authority.rpartition("@")
        if ":" in userinfo:  # inline password already present — leave it
            return raw
        return f"{scheme}{sep}{userinfo}:{quote(password, safe='')}{at}{hostport}{slash}{tail}"


class TlsSettings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    # CA bundle used to verify `rediss://` Redis. Unset = plain Redis (the default).
    ca_cert_path: str | None = Field(None, validation_alias="INTERNAL_CA_CERT_PATH")


class UpstreamSettings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    # The agents service: runs the agents and streams AG-UI events back.
    agents_service_url: str = Field("http://agents:8003", validation_alias="AGENTS_SERVICE_URL")
    # A new audit starts its pipeline on the agents service (POST /audits/{id}/run).
    audit_pipeline_autostart: bool = Field(True, validation_alias="AUDIT_PIPELINE_AUTOSTART")
    # The risk classifier (POST /systems/{id}/classify) is awaited this long (s).
    classify_timeout_s: float = Field(120.0, gt=0, validation_alias="CLASSIFY_TIMEOUT_S")
    # Optional shared secret sent to the agents service as X-Internal-Service-Secret.
    agents_service_secret: SecretStr = Field(
        default_factory=lambda: SecretStr(""), validation_alias="AGENTS_SERVICE_SECRET"
    )

    @field_validator("agents_service_secret", mode="before")
    @classmethod
    def _load_secret(cls, value: object) -> object:
        if isinstance(value, str) and value:
            return value
        return _resolve_file_backed_secret("AGENTS_SERVICE_SECRET") or ""


class RegMemorySettings(BaseSettings):
    """reg-memory (the regulation store): the backend proxies ``/v1/regulation``."""

    model_config = _BASE_MODEL_CONFIG

    url: str = Field("http://reg-memory:8010", validation_alias="REG_MEMORY_URL")
    # Sent as X-Internal-Secret.
    secret: SecretStr = Field(
        default_factory=lambda: SecretStr(""), validation_alias="REG_MEMORY_INTERNAL_SECRET"
    )
    timeout_seconds: float = Field(30.0, validation_alias="REG_MEMORY_TIMEOUT_SECONDS")
    # check-now with wait: true downloads and diffs; give it longer.
    check_timeout_seconds: float = Field(300.0, validation_alias="REG_MEMORY_CHECK_TIMEOUT_SECONDS")


class MlflowSettings(BaseSettings):
    """The local MLflow registry: the plugin form reads a model's version, description and
    signature from it to prefill a new plugin (utils/plugins.py). Read-only."""

    model_config = _BASE_MODEL_CONFIG

    tracking_uri: str = Field("http://mlflow:5000", validation_alias="MLFLOW_TRACKING_URI")
    timeout_seconds: float = Field(5.0, validation_alias="MLFLOW_TIMEOUT_SECONDS")


class TelegramSettings(BaseSettings):
    """HITL approvals over Telegram. No token = every Telegram call is a no-op."""

    model_config = _BASE_MODEL_CONFIG

    bot_token: SecretStr = Field(
        default_factory=lambda: SecretStr(""), validation_alias="TELEGRAM_BOT_TOKEN"
    )
    # Allow-list: the chats that receive gates and may decide them (comma-separated ids).
    chat_ids: Annotated[tuple[str, ...], NoDecode] = Field((), validation_alias="TELEGRAM_CHAT_ID")
    api_url: str = Field("https://api.telegram.org", validation_alias="TELEGRAM_API_URL")
    # Set = webhook mode (Telegram POSTs to it; route /telegram/webhook); empty = long polling.
    webhook_url: str = Field("", validation_alias="TELEGRAM_WEBHOOK_URL")
    # Checked against X-Telegram-Bot-Api-Secret-Token in webhook mode.
    webhook_secret: SecretStr = Field(
        default_factory=lambda: SecretStr(""), validation_alias="TELEGRAM_WEBHOOK_SECRET"
    )
    poll_timeout_seconds: int = Field(25, ge=1, le=50, validation_alias="TELEGRAM_POLL_TIMEOUT")
    # Base of the "Open in app" links.
    app_public_url: str = Field("http://localhost:8080", validation_alias="APP_PUBLIC_URL")

    @field_validator("chat_ids", mode="before")
    @classmethod
    def _split(cls, value: object) -> tuple[str, ...]:
        return _split_csv(value)

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token.get_secret_value())


class InferenceSettings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    # Cap stored TOOL_CALL_RESULT content in the per-run event log; oversized
    # results are cut and flagged with "truncated": true so the UI can say so.
    tool_result_max_chars: int = Field(16000, validation_alias="INFERENCE_TOOL_RESULT_MAX_CHARS")
    ws_subscribe_timeout_seconds: float = Field(
        10.0, validation_alias="INFERENCE_WS_SUBSCRIBE_TIMEOUT_SECONDS"
    )
    # Several approvals answered together go to the agents service in ONE
    # resume, keyed by interrupt id. Off: one resume per decision, in order.
    batch_hitl_resume: bool = Field(True, validation_alias="INFERENCE_BATCH_HITL_RESUME")


class AttachmentSettings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    max_size_bytes: int = Field(25 * 1024 * 1024, validation_alias="ATTACHMENT_MAX_SIZE_BYTES")
    max_total_bytes: int = Field(25 * 1024 * 1024, validation_alias="ATTACHMENT_MAX_TOTAL_BYTES")
    max_per_message: int = Field(10, validation_alias="ATTACHMENT_MAX_PER_MESSAGE")
    docx_preview_token_ttl_seconds: int = Field(
        60, validation_alias="ATTACHMENT_DOCX_PREVIEW_TOKEN_TTL_SECONDS"
    )
    inline_cache_max_age_seconds: int = Field(
        300, validation_alias="ATTACHMENT_INLINE_CACHE_MAX_AGE_SECONDS"
    )
    stream_chunk_bytes: int = Field(512 * 1024, validation_alias="ATTACHMENT_STREAM_CHUNK_BYTES")


class WorkspaceSettings(BaseSettings):
    """System folders, memory files and audits (utils/workspace.py, utils/seed_import.py)."""

    model_config = _BASE_MODEL_CONFIG

    # Largest single workspace file (system dossier, plugin docs, memory entry).
    max_file_bytes: int = Field(10 * 1024 * 1024, validation_alias="WORKSPACE_MAX_FILE_BYTES")
    # The seed case folders (SYS-00X/) that POST /v1/admin/import-seed reads.
    seed_cases_dir: str = Field("/seed-cases", validation_alias="SEED_CASES_DIR")


class ConversationSettings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    max_pinned: int = Field(30, ge=1, le=100, validation_alias="MAX_PINNED_CONVERSATIONS")
    # The per-conversation channel (a Redis stream: run started, queued message).
    channel_maxlen: int = Field(
        500, ge=10, le=100000, validation_alias="CONVERSATION_CHANNEL_MAXLEN"
    )
    channel_ttl_seconds: int = Field(
        86400, ge=60, validation_alias="CONVERSATION_CHANNEL_TTL_SECONDS"
    )
    channel_read_block_ms: int = Field(
        5000, ge=100, le=60000, validation_alias="CONVERSATION_CHANNEL_READ_BLOCK_MS"
    )


class AsyncTaskSettings(BaseSettings):
    """Background sub-agent tasks: the backend's half.

    The agents service runs the tasks and announces them on Redis streams; the
    backend mirrors them for the UI, relays their events, wakes the
    orchestrator when a depth-1 task's subtree settles, and sends the
    composer's queued message when a run ends. These knobs bound how much of
    that one process does at once.
    """

    model_config = _BASE_MODEL_CONFIG

    # Kill switch for the Redis consumers and the reconcile loop (the routes
    # and the mirror stay). Off = no wake-ups, no live task frames.
    enabled: bool = Field(True, validation_alias="ASYNC_TASKS_ENABLED")
    # This process's name in the `backend` consumer group. Empty = the host
    # name, so overlapping replicas never share pending entries.
    consumer_name: str = Field("", validation_alias="ASYNC_TASKS_CONSUMER_NAME")
    # How long one XREADGROUP blocks, and how many entries it takes.
    read_block_ms: int = Field(5000, ge=100, le=60000, validation_alias="ASYNC_TASKS_READ_BLOCK_MS")
    read_count: int = Field(50, ge=1, le=1000, validation_alias="ASYNC_TASKS_READ_COUNT")
    # An entry another consumer left pending this long is taken over.
    claim_idle_ms: int = Field(60000, ge=1000, validation_alias="ASYNC_TASKS_CLAIM_IDLE_MS")
    # The reconcile loop: unnotified settles from the agents service, and
    # queued composer messages whose run ended without sending them.
    reconcile_interval_seconds: int = Field(
        60, ge=5, le=3600, validation_alias="ASYNC_TASKS_RECONCILE_INTERVAL_SECONDS"
    )
    unnotified_limit: int = Field(
        100, ge=1, le=1000, validation_alias="ASYNC_TASKS_UNNOTIFIED_LIMIT"
    )
    # A queued message older than this with no active run is sent by the loop.
    queue_sweep_after_seconds: int = Field(
        15, ge=1, le=3600, validation_alias="ASYNC_TASKS_QUEUE_SWEEP_AFTER_SECONDS"
    )
    # A wake-up refused with 429 (the client's active-run cap) is retried this
    # many times, waiting base * 2^n seconds; then the reconcile loop owns it.
    wake_retry_attempts: int = Field(
        3, ge=0, le=10, validation_alias="ASYNC_TASKS_WAKE_RETRY_ATTEMPTS"
    )
    wake_retry_base_seconds: float = Field(
        2.0, ge=0.0, le=60.0, validation_alias="ASYNC_TASKS_WAKE_RETRY_BASE_SECONDS"
    )
    # Wake-ups the outbox consumer handles at once.
    wake_concurrency: int = Field(4, ge=1, le=64, validation_alias="ASYNC_TASKS_WAKE_CONCURRENCY")
    # Events kept in conversation_tasks.raw_events per task (after coalescing);
    # past it the oldest are dropped behind one truncation marker.
    raw_events_max: int = Field(
        5000, ge=100, le=100000, validation_alias="ASYNC_TASKS_RAW_EVENTS_MAX"
    )
    # The task drill-down socket checks for a settled task this often while
    # its event stream is quiet.
    task_ws_block_ms: int = Field(
        5000, ge=100, le=60000, validation_alias="ASYNC_TASKS_TASK_WS_BLOCK_MS"
    )
    # Tasks one GET /v1/conversations/{id}/tasks returns at most.
    list_limit_max: int = Field(500, ge=1, le=5000, validation_alias="ASYNC_TASKS_LIST_LIMIT_MAX")


class HttpTimeoutSettings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    agents_connect_seconds: float = Field(10.0, validation_alias="HTTP_AGENTS_CONNECT_SECONDS")
    agents_read_seconds: float = Field(30.0, validation_alias="HTTP_AGENTS_READ_SECONDS")
    agents_write_seconds: float = Field(30.0, validation_alias="HTTP_AGENTS_WRITE_SECONDS")
    agents_pool_seconds: float = Field(10.0, validation_alias="HTTP_AGENTS_POOL_SECONDS")

    inference_connect_seconds: float = Field(
        30.0, validation_alias="HTTP_INFERENCE_CONNECT_SECONDS"
    )
    inference_read_seconds: float = Field(180.0, validation_alias="HTTP_INFERENCE_READ_SECONDS")
    inference_write_seconds: float = Field(180.0, validation_alias="HTTP_INFERENCE_WRITE_SECONDS")
    inference_pool_seconds: float = Field(30.0, validation_alias="HTTP_INFERENCE_POOL_SECONDS")

    @property
    def agents_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self.agents_connect_seconds,
            read=self.agents_read_seconds,
            write=self.agents_write_seconds,
            pool=self.agents_pool_seconds,
        )

    @property
    def inference_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self.inference_connect_seconds,
            read=self.inference_read_seconds,
            write=self.inference_write_seconds,
            pool=self.inference_pool_seconds,
        )


class RedisSettings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    url: str = Field("redis://redis:6379/0", validation_alias="REDIS_URL")
    password: SecretStr = Field(default_factory=lambda: SecretStr(""))
    stream_maxlen: int = Field(20000, validation_alias="REDIS_STREAM_MAXLEN")
    terminal_ttl_seconds: int = Field(3600, validation_alias="REDIS_STREAM_TERMINAL_TTL_SECONDS")
    read_block_ms: int = Field(30000, validation_alias="REDIS_STREAM_READ_BLOCK_MS")

    @field_validator("password", mode="before")
    @classmethod
    def _load_password(cls, value: object) -> object:
        if isinstance(value, SecretStr) and value.get_secret_value():
            return value
        if isinstance(value, str) and value:
            return value
        return _resolve_file_backed_secret("REDIS_PASSWORD") or ""


class RateLimitSettings(BaseSettings):
    """Every limit, env-tunable. See core/security/rate_limit.py for the keys."""

    model_config = _BASE_MODEL_CONFIG

    # Global budget per client IP across every endpoint. Generous on purpose:
    # at a venue many people share one IP (NAT).
    ip_max_calls: int = Field(1200, validation_alias="IP_RATE_LIMIT_MAX_CALLS")
    ip_window_seconds: int = Field(60, validation_alias="IP_RATE_LIMIT_WINDOW_SECONDS")
    # Starting a run spends model calls — the tightest bucket.
    inference_max_attempts: int = Field(10, validation_alias="INFERENCE_RATE_LIMIT_MAX_ATTEMPTS")
    inference_window_seconds: int = Field(
        60, validation_alias="INFERENCE_RATE_LIMIT_WINDOW_SECONDS"
    )
    inference_max_active_runs: int = Field(
        5, validation_alias="INFERENCE_MAX_ACTIVE_RUNS_PER_CLIENT"
    )
    # Writing messages / uploads grows storage.
    message_post_max_attempts: int = Field(30, validation_alias="MESSAGE_RATE_LIMIT_MAX_ATTEMPTS")
    message_post_window_seconds: int = Field(
        60, validation_alias="MESSAGE_RATE_LIMIT_WINDOW_SECONDS"
    )
    # Conversation reads/writes (list, rename, archive, pin, fork, delete).
    conversation_max_attempts: int = Field(
        240, validation_alias="CONVERSATION_RATE_LIMIT_MAX_ATTEMPTS"
    )
    conversation_window_seconds: int = Field(
        60, validation_alias="CONVERSATION_RATE_LIMIT_WINDOW_SECONDS"
    )
    search_max_attempts: int = Field(60, validation_alias="SEARCH_RATE_LIMIT_MAX_ATTEMPTS")
    search_window_seconds: int = Field(60, validation_alias="SEARCH_RATE_LIMIT_WINDOW_SECONDS")
    # Background tasks: reading the tree, and acting on a task (stop, approve,
    # drop the queued message) — each act is one agents-service call.
    task_read_max_attempts: int = Field(120, validation_alias="TASK_READ_RATE_LIMIT_MAX_ATTEMPTS")
    task_read_window_seconds: int = Field(
        60, validation_alias="TASK_READ_RATE_LIMIT_WINDOW_SECONDS"
    )
    task_mutate_max_attempts: int = Field(
        30, validation_alias="TASK_MUTATE_RATE_LIMIT_MAX_ATTEMPTS"
    )
    task_mutate_window_seconds: int = Field(
        60, validation_alias="TASK_MUTATE_RATE_LIMIT_WINDOW_SECONDS"
    )
    # Systems, workspace files, memory and audits (reads and writes).
    workspace_max_attempts: int = Field(240, validation_alias="WORKSPACE_RATE_LIMIT_MAX_ATTEMPTS")
    workspace_window_seconds: int = Field(
        60, validation_alias="WORKSPACE_RATE_LIMIT_WINDOW_SECONDS"
    )
    # The agents service's internal API (keyed by IP: it sends no client id).
    internal_max_attempts: int = Field(1200, validation_alias="INTERNAL_RATE_LIMIT_MAX_ATTEMPTS")
    internal_window_seconds: int = Field(60, validation_alias="INTERNAL_RATE_LIMIT_WINDOW_SECONDS")
    # WebSocket handshakes (the SDK middleware is HTTP-only).
    ws_connect_max_attempts: int = Field(20, validation_alias="WS_CONNECT_RATE_LIMIT_MAX_ATTEMPTS")
    ws_connect_window_seconds: int = Field(
        60, validation_alias="WS_CONNECT_RATE_LIMIT_WINDOW_SECONDS"
    )


class ClientSettings(BaseSettings):
    """How the backend identifies the caller without login."""

    model_config = _BASE_MODEL_CONFIG

    # The browser sends a random UUID it keeps in localStorage. It scopes
    # conversations and per-route rate limits; it is NOT authentication.
    client_id_header: str = Field("X-Client-Id", validation_alias="CLIENT_ID_HEADER")
    # Trust X-Forwarded-For (first hop) for the client IP. Turn on only when the
    # backend is reachable solely through a reverse proxy that sets it.
    trust_forwarded_for: bool = Field(False, validation_alias="TRUST_FORWARDED_FOR")


class LangfuseSettings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    host: str = Field("http://langfuse-web:3000", validation_alias="LANGFUSE_HOST")
    public_key: str = Field("", validation_alias="LANGFUSE_PUBLIC_KEY")
    secret_key: SecretStr = Field(
        default_factory=lambda: SecretStr(""), validation_alias="LANGFUSE_SECRET_KEY"
    )

    @property
    def enabled(self) -> bool:
        return bool(self.public_key and self.secret_key.get_secret_value())


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


class CorsSettings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    # NoDecode: pydantic-settings would otherwise JSON-decode a tuple env value.
    allowed_origins: Annotated[tuple[str, ...], NoDecode] = Field(
        default=("http://localhost:5173", "http://localhost:8080", "http://127.0.0.1:8080"),
        validation_alias="CORS_ALLOWED_ORIGINS",
    )
    allow_credentials: bool = Field(False, validation_alias="CORS_ALLOW_CREDENTIALS")
    allow_methods: Annotated[tuple[str, ...], NoDecode] = Field(
        default=("GET", "POST", "PUT", "PATCH", "DELETE"),
        validation_alias="CORS_ALLOW_METHODS",
    )
    allow_headers: Annotated[tuple[str, ...] | None, NoDecode] = Field(
        default=None, validation_alias="CORS_ALLOW_HEADERS"
    )
    expose_headers: Annotated[tuple[str, ...], NoDecode] = Field(
        default=(
            "Content-Disposition",
            "Content-Length",
            "Content-Range",
            "Accept-Ranges",
            "Retry-After",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
        ),
        validation_alias="CORS_EXPOSE_HEADERS",
    )
    max_age_seconds: int = Field(600, validation_alias="CORS_MAX_AGE_SECONDS")

    @field_validator(
        "allowed_origins", "allow_methods", "expose_headers", "allow_headers", mode="before"
    )
    @classmethod
    def _parse_csv(cls, v: object) -> object:
        if v is None or isinstance(v, list | tuple):
            return v
        return _split_csv(v)

    @model_validator(mode="after")
    def _apply_defaults_and_validate(self) -> CorsSettings:
        if not self.allow_headers:
            object.__setattr__(
                self,
                "allow_headers",
                ("Accept", "Content-Type", "Range", "If-Range", "X-Client-Id", "X-Request-Id"),
            )
        if self.allow_credentials and "*" in self.allowed_origins:
            raise ValueError(
                "CORS_ALLOWED_ORIGINS cannot contain '*' when CORS_ALLOW_CREDENTIALS is enabled."
            )
        return self


class Settings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    app: AppSettings = Field(default_factory=AppSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    tls: TlsSettings = Field(default_factory=TlsSettings)
    upstream: UpstreamSettings = Field(default_factory=UpstreamSettings)
    reg_memory: RegMemorySettings = Field(default_factory=RegMemorySettings)
    mlflow: MlflowSettings = Field(default_factory=MlflowSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    inference: InferenceSettings = Field(default_factory=InferenceSettings)
    attachments: AttachmentSettings = Field(default_factory=AttachmentSettings)
    workspace: WorkspaceSettings = Field(default_factory=WorkspaceSettings)
    conversations: ConversationSettings = Field(default_factory=ConversationSettings)
    async_tasks: AsyncTaskSettings = Field(default_factory=AsyncTaskSettings)
    http: HttpTimeoutSettings = Field(default_factory=HttpTimeoutSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    client: ClientSettings = Field(default_factory=ClientSettings)
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    cors: CorsSettings = Field(default_factory=CorsSettings)

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        # Outside development the localhost CORS defaults must not follow the
        # backend into a deployment.
        if self.app.env not in _LOCAL_ENVS:
            local = [o for o in self.cors.allowed_origins if not _is_public_https_origin(o)]
            if local:
                raise ValueError(
                    "CORS_ALLOWED_ORIGINS must list only https origins on public hosts when "
                    f"APP_ENV={self.app.env!r}; refusing {local}."
                )
        if not self.logging.redaction_secret.get_secret_value():
            # IDs in logs are HMAC'd; without a configured secret use a per-boot
            # random one (log correlation then holds only within one process).
            object.__setattr__(self.logging, "redaction_secret", SecretStr(os.urandom(32).hex()))
        return self


settings = Settings()
