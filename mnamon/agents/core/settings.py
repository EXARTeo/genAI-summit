"""Agents-service configuration, read from the environment (and `.env` in development).

Every value has a safe development default. Secrets also accept a ``<NAME>_FILE``
indirection (a Docker secret file). Outside development (``APP_ENV`` other than
``development``/``test``) the service refuses to start without
``INTERNAL_SERVICE_SECRET``, so a deployed agents service is never open to any
caller on its network.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Annotated

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_BASE_MODEL_CONFIG = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
    case_sensitive=False,
)

#: Environments where an unset internal secret is tolerated (no caller check).
_LOCAL_ENVS = frozenset({"development", "test"})

#: Where the product's agent definitions live (``<slug>/agent.yaml``). Empty
#: until the product agent is written.
_DEFAULT_AGENTS_DIR = Path(__file__).resolve().parents[1] / "definitions"


def _resolve_file_backed_secret(*env_names: str) -> str | None:
    """Read a secret from ``<NAME>_FILE`` or the env var itself, first hit wins.

    An unreadable ``*_FILE`` path raises instead of silently falling through to
    an unset secret.
    """
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


def _secret_or_file(value: object, *env_names: str) -> object:
    """A ``before`` validator body: an explicit value wins, else the env/file secret."""
    if isinstance(value, SecretStr) and value.get_secret_value():
        return value
    if isinstance(value, str) and value.strip():
        return value.strip()
    return _resolve_file_backed_secret(*env_names) or ""


class AppSettings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    service_name: str = Field("agents", validation_alias="LOG_SERVICE_NAME")
    env: str = Field("development", validation_alias=AliasChoices("APP_ENV", "ENV"))
    version: str = Field("unknown", validation_alias=AliasChoices("APP_VERSION", "IMAGE_TAG"))

    @property
    def is_local(self) -> bool:
        """Development or test: the only environments that may run without a secret."""
        return self.env.strip().lower() in _LOCAL_ENVS


class ApiKeysSettings(BaseSettings):
    """Provider keys. Google Gemini is the only LLM provider of the product."""

    model_config = _BASE_MODEL_CONFIG

    google: SecretStr = Field(default_factory=lambda: SecretStr(""))

    @field_validator("google", mode="before")
    @classmethod
    def _load_google(cls, value: object) -> object:
        return _secret_or_file(value, "GOOGLE_API_KEY", "GEMINI_API_KEY")


class GeminiSettings(BaseSettings):
    """Model access (``harness/models/gemini.py``): Gemini through ``langchain-google-genai``.

    ``GEMINI_MODEL`` runs every step by default; ``GEMINI_MODEL_REASONING`` (empty =
    the default model) runs the judgement-heavy steps (planning, critic, change
    judge). ``AGENTS_FAKE_LLM`` swaps every pipeline model for a deterministic stub
    (dry runs and demos without a key); it never calls a provider.
    """

    model_config = _BASE_MODEL_CONFIG

    model: str = Field("gemini-3.5-flash-lite", validation_alias="GEMINI_MODEL")
    reasoning_model: str = Field("", validation_alias="GEMINI_MODEL_REASONING")
    temperature: float | None = Field(None, ge=0, le=2, validation_alias="GEMINI_TEMPERATURE")
    timeout_seconds: float = Field(120.0, gt=0, le=900, validation_alias="GEMINI_TIMEOUT_SECONDS")
    max_retries: int = Field(2, ge=0, le=10, validation_alias="GEMINI_MAX_RETRIES")
    fake_llm: bool = Field(False, validation_alias="AGENTS_FAKE_LLM")

    @field_validator("model", "reasoning_model", mode="before")
    @classmethod
    def _strip_model(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class PipelineSettings(BaseSettings):
    """The audit and impact pipelines (``pipeline/``): where they read and write.

    The backend's internal API takes the same shared secret the backend sends
    here (``INTERNAL_SERVICE_SECRET``); reg-memory has its own.
    """

    model_config = _BASE_MODEL_CONFIG

    backend_internal_url: str = Field(
        "http://backend:8000", validation_alias="BACKEND_INTERNAL_URL"
    )
    reg_memory_url: str = Field("http://reg-memory:8010", validation_alias="REG_MEMORY_URL")
    reg_memory_secret: SecretStr = Field(default_factory=lambda: SecretStr(""))
    # Redos of one step after human rejections before the audit stops as rejected.
    max_redos: int = Field(3, ge=1, le=10, validation_alias="PIPELINE_MAX_REDOS")
    # Automatic redos when a deterministic verifier fails a step's output
    # (scenarios-check high gaps, invalid spec, failed dataset gate, ungrounded evidence).
    max_auto_redos: int = Field(1, ge=0, le=3, validation_alias="PIPELINE_MAX_AUTO_REDOS")
    seed: int = Field(42, validation_alias="PIPELINE_SEED")
    sandbox_timeout_seconds: int = Field(
        600, ge=30, le=900, validation_alias="PIPELINE_SANDBOX_TIMEOUT_SECONDS"
    )
    http_timeout_seconds: float = Field(
        60.0, gt=0, validation_alias="PIPELINE_HTTP_TIMEOUT_SECONDS"
    )
    # Public dataset search reaches the internet; off = always zero-shot.
    public_data_enabled: bool = Field(True, validation_alias="PIPELINE_PUBLIC_DATA_ENABLED")
    # The decision model (pipeline/decision.py) per task: Oumi Iris first, Gemini
    # as the fallback. The change judge defaults to gemini, the scenario review to iris.
    decision_model: str = Field(
        "gemini", pattern=r"^(gemini|iris)$", validation_alias="CHANGE_JUDGE_MODEL"
    )
    scenario_review_model: str = Field(
        "iris", pattern=r"^(iris|gemini|off)$", validation_alias="SCENARIO_REVIEW_MODEL"
    )
    # Oumi's decision-model API: POST {OUMI_BASE_URL}/systemone, header X-API-Key,
    # model = projects/<project_id>/models/iris-latest (docs.oumi.ai, decision models).
    oumi_api_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    oumi_base_url: str = Field("https://inference.oumi.ai/v1", validation_alias="OUMI_BASE_URL")
    oumi_model: str = Field("", validation_alias="OUMI_MODEL")
    oumi_timeout_seconds: float = Field(20.0, gt=0, le=120, validation_alias="OUMI_TIMEOUT_SECONDS")

    @field_validator("decision_model", "scenario_review_model", "oumi_base_url", mode="before")
    @classmethod
    def _empty_is_default(cls, value: object, info: ValidationInfo) -> object:
        """An empty value (``CHANGE_JUDGE_MODEL=`` in .env) means the field's default."""
        if isinstance(value, str) and not value.strip():
            return cls.model_fields[str(info.field_name)].default
        return value.strip() if isinstance(value, str) else value

    @field_validator("oumi_model", mode="before")
    @classmethod
    def _strip_oumi_model(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("reg_memory_secret", mode="before")
    @classmethod
    def _load_reg_memory_secret(cls, value: object) -> object:
        return _secret_or_file(value, "REG_MEMORY_INTERNAL_SECRET")

    @field_validator("oumi_api_key", mode="before")
    @classmethod
    def _load_oumi_key(cls, value: object) -> object:
        return _secret_or_file(value, "OUMI_API_KEY")


class McpSettings(BaseSettings):
    """The MCP gateway (sibling ``mcp_gateway``), an optional add-on.

    Empty ``MCP_GATEWAY_URL`` means runs use the agent's own tools only. A
    configured gateway that cannot be reached within ``connect_timeout_seconds``
    degrades a run the same way (logged) instead of failing it.
    """

    model_config = _BASE_MODEL_CONFIG

    mcp_gateway_url: str = Field("", validation_alias="MCP_GATEWAY_URL")
    manifest_cache_enabled: bool = Field(True, validation_alias="MCP_MANIFEST_CACHE_ENABLED")
    connect_timeout_seconds: float = Field(
        10.0, gt=0, le=120, validation_alias="MCP_CONNECT_TIMEOUT_SECONDS"
    )

    @property
    def enabled(self) -> bool:
        """True when a gateway URL is configured: the one "is MCP on" check."""
        return bool(self.mcp_gateway_url.strip())


class TlsSettings(BaseSettings):
    """The CA a ``rediss://`` Redis is verified against (unset for plain ``redis://``)."""

    model_config = _BASE_MODEL_CONFIG

    ca_cert_path: str | None = Field(None, validation_alias="INTERNAL_CA_CERT_PATH")


class CheckpointerSettings(BaseSettings):
    """The ``agent_runtime`` Postgres database: checkpoints, files, scratch, tasks.

    A raw psycopg conninfo (``postgresql://``), on the same Postgres as the
    backend's database. The lifespan creates the database when it is missing.
    """

    model_config = _BASE_MODEL_CONFIG

    url: SecretStr = Field(
        default=SecretStr("postgresql://postgres:postgres@postgres:5432/agent_runtime"),
        validation_alias="AGENT_RUNTIME_DATABASE_URL",
    )
    pool_min_size: int = Field(2, validation_alias="AGENT_RUNTIME_POOL_MIN_SIZE")
    pool_max_size: int = Field(20, validation_alias="AGENT_RUNTIME_POOL_MAX_SIZE")
    pool_max_idle: int = Field(300, validation_alias="AGENT_RUNTIME_POOL_MAX_IDLE")
    pool_timeout: float = Field(30.0, validation_alias="AGENT_RUNTIME_POOL_TIMEOUT")
    # Run the idempotent DDL (checkpointer, files, scratch, tasks) on startup.
    setup_on_startup: bool = Field(True, validation_alias="AGENT_RUNTIME_SETUP_ON_STARTUP")
    # Strict msgpack deserialization allow-list (blocks the JsonPlusSerializer
    # RCE class, CVE-2025-64439). Exported into the env the langgraph lib reads.
    strict_msgpack: bool = Field(True, validation_alias="LANGGRAPH_STRICT_MSGPACK")
    # AES key (16/24/32 bytes) for at-rest encryption of checkpoints and
    # conversation files. Empty means plaintext (local development).
    aes_key: SecretStr = Field(default_factory=lambda: SecretStr(""))

    @field_validator("url", mode="before")
    @classmethod
    def _load_url(cls, value: object) -> object:
        return _secret_or_file(value, "AGENT_RUNTIME_DATABASE_URL")

    @field_validator("aes_key", mode="before")
    @classmethod
    def _load_aes_key(cls, value: object) -> object:
        return _secret_or_file(value, "LANGGRAPH_AES_KEY")


class ProxySettings(BaseSettings):
    """The internal-caller secret: ``X-Internal-Service-Secret`` on every request.

    The backend sends it (``AGENTS_SERVICE_SECRET`` there, the same value);
    the in-process async-task transport sends it too. Unset is allowed only in
    development and test, where every caller is accepted.
    """

    model_config = _BASE_MODEL_CONFIG

    internal_service_secret: SecretStr = Field(default_factory=lambda: SecretStr(""))

    @field_validator("internal_service_secret", mode="before")
    @classmethod
    def _load_secret(cls, value: object) -> object:
        return _secret_or_file(value, "INTERNAL_SERVICE_SECRET")


_DEFAULT_REDACTION_SECRET = "agents-log-redaction"  # noqa: S105 - replaced at load


class LoggingSettings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    level: str = Field("INFO", validation_alias="LOG_LEVEL")
    format: str = Field("console", validation_alias="LOG_FORMAT")
    timezone: str = Field("Europe/Athens", validation_alias=AliasChoices("LOG_TIMEZONE", "TZ"))
    # Keys the ``h:<16 hex>`` identifier hashes. Set it to the backend's value so
    # a client's hash is the same in both services' logs and traces.
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
        return _secret_or_file(value, "LOG_REDACTION_SECRET") or _DEFAULT_REDACTION_SECRET


class ModelInfo(BaseModel):
    """What the service knows about one model beyond the pinned LangChain's table.

    A model newer than the pinned provider package needs its facts stated
    here; an older one falls back to LangChain's.
    """

    model_config = ConfigDict(extra="forbid")

    # A reasoning model is asked for its reasoning summary; a non-reasoning
    # model would reject that parameter.
    reasoning: bool | None = None
    # Max input tokens: compaction needs it.
    context_window: int | None = Field(None, gt=0)


class AgentRegistrySettings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    # Folder of declarative agents (``<slug>/agent.yaml``), read at boot.
    agents_dir: Path = Field(_DEFAULT_AGENTS_DIR, validation_alias="AGENTS_DIR")
    # The agent GET /agents marks as the default for a new conversation (none
    # by default: there is no built-in agent).
    default_agent_slug: str | None = Field(None, validation_alias="DEFAULT_AGENT_SLUG")
    # Model facts, ``provider:model`` -> ModelInfo, as JSON in the env.
    models: Annotated[dict[str, ModelInfo], NoDecode] = Field(
        default_factory=lambda: {
            "google_genai:gemini-3.5-flash-lite": ModelInfo(context_window=1_048_576),
            "google_genai:gemini-3.5-flash": ModelInfo(context_window=1_048_576),
            "google_genai:gemini-3.5-pro": ModelInfo(context_window=1_048_576),
        },
        validation_alias="AGENT_MODELS",
    )

    @field_validator("models", mode="before")
    @classmethod
    def _parse_models(cls, value: object) -> object:
        return json.loads(value) if isinstance(value, str) and value.strip() else value


class ModelProfileSettings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    # OpenAI returns a reasoning model's reasoning only as its own summary,
    # streamed as THINKING events. off asks for none.
    reasoning_summary: str = Field(
        "auto", pattern=r"^(auto|concise|detailed|off)$", validation_alias="REASONING_SUMMARY"
    )


class FilesystemSettings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    # Ceiling on an image handed to the model by `view_image` (context cost).
    view_image_max_bytes: int = Field(10485760, validation_alias="VIEW_IMAGE_MAX_BYTES")
    # A presented file rides PRESENT_ARTIFACT as base64 up to this size (the
    # backend's attachment limit); a bigger one is presented without its bytes.
    output_max_file_bytes: int = Field(26214400, validation_alias="OUTPUT_MAX_FILE_BYTES")
    # Presented files per run that carry their bytes.
    output_max_files: int = Field(20, validation_alias="OUTPUT_MAX_FILES")

    # Sandbox-execution kill switch (fail-closed): deepagents exposes `execute`
    # exactly when the default backend can execute, and workspace assembly
    # refuses to mint one while this is off.
    sandbox_execution_enabled: bool = Field(False, validation_alias="SANDBOX_EXECUTION_ENABLED")
    # The sandbox runner `execute` calls (sibling ``sandbox``), e.g.
    # http://sandbox_runner:8090. Empty keeps execution off whatever the flag says.
    sandbox_runner_url: str = Field("", validation_alias="SANDBOX_RUNNER_URL")
    # The runner's TRUSTED_PROXY_SECRET, sent as X-Internal-Proxy-Secret.
    # Unset means INTERNAL_SERVICE_SECRET (one shared secret, as the compose sets it).
    sandbox_runner_secret: SecretStr = Field(default_factory=lambda: SecretStr(""))
    # Read timeout of one /v1/exec call; longer than the runner's own wall-clock
    # kill so a slow command comes back as the runner's `timeout` result.
    sandbox_runner_timeout_seconds: float = Field(
        330.0, gt=0, le=3600, validation_alias="SANDBOX_RUNNER_TIMEOUT_SECONDS"
    )
    sandbox_runner_connect_timeout_seconds: float = Field(
        10.0, gt=0, le=120, validation_alias="SANDBOX_RUNNER_CONNECT_TIMEOUT_SECONDS"
    )

    @field_validator("sandbox_runner_url", mode="before")
    @classmethod
    def _strip_runner_url(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("sandbox_runner_secret", mode="before")
    @classmethod
    def _load_runner_secret(cls, value: object) -> object:
        return _secret_or_file(value, "SANDBOX_RUNNER_SECRET", "INTERNAL_SERVICE_SECRET")

    @property
    def sandbox_execution_active(self) -> bool:
        """Whether this deployment has `execute`: the switch is on AND a runner is set."""
        return self.sandbox_execution_enabled and bool(self.sandbox_runner_url)


class ConversationFilesSettings(BaseSettings):
    """A conversation's files, stored in ``agent_runtime``.

    The per-file cap is a technical safety limit (one file is held in memory
    while it is encrypted, written or read), not a storage policy.
    """

    model_config = _BASE_MODEL_CONFIG

    max_file_bytes: int = Field(
        100 * 1024 * 1024, ge=1, validation_alias="CONVERSATION_FILE_MAX_BYTES"
    )


class MemorySettings(BaseSettings):
    """Agent memory per audited system (``harness/memory``, table ``system_memories``)."""

    model_config = _BASE_MODEL_CONFIG

    # New entries per system; updates to an existing entry always go through.
    max_entries_per_system: int = Field(
        200, ge=1, le=10000, validation_alias="MEMORY_MAX_ENTRIES_PER_SYSTEM"
    )


class SummarizationSettings(BaseSettings):
    """Context compaction: summarize at 95% of a model's window.

    The fraction knobs apply to models with a window; the token/message knobs
    are the fallback for models without one.
    """

    model_config = _BASE_MODEL_CONFIG

    trigger_fraction: float = Field(0.95, validation_alias="SUMMARIZATION_TRIGGER_FRACTION")
    keep_fraction: float = Field(0.30, validation_alias="SUMMARIZATION_KEEP_FRACTION")
    trigger_tokens: int = Field(200000, validation_alias="SUMMARIZATION_TRIGGER_TOKENS")
    keep_messages: int = Field(20, validation_alias="SUMMARIZATION_KEEP_MESSAGES")


class RateLimitRetrySettings(BaseSettings):
    """Waiting out a provider rate limit (HTTP 429) instead of failing the run.

    A per-minute token quota needs longer than the OpenAI client's own short
    backoff, so ``RetryOnRateLimitMiddleware`` waits and re-issues the call. A
    429 is refused before any token streams, so a retry never duplicates output.
    """

    model_config = _BASE_MODEL_CONFIG

    max_attempts: int = Field(4, ge=1, le=10, validation_alias="MODEL_RATE_LIMIT_RETRY_ATTEMPTS")
    delay_seconds: float = Field(
        15.0, ge=0, validation_alias="MODEL_RATE_LIMIT_RETRY_DELAY_SECONDS"
    )
    max_delay_seconds: float = Field(
        120.0, ge=0, validation_alias="MODEL_RATE_LIMIT_RETRY_MAX_DELAY_SECONDS"
    )


class AguiSettings(BaseSettings):
    """Bounds on what the AG-UI stream carries: an image tool result becomes a thumbnail."""

    model_config = _BASE_MODEL_CONFIG

    image_preview_max_edge: int = Field(512, validation_alias="AGUI_IMAGE_PREVIEW_MAX_EDGE")
    image_preview_max_bytes: int = Field(49152, validation_alias="AGUI_IMAGE_PREVIEW_MAX_BYTES")


class RedisSettings(BaseSettings):
    """The Redis the async-task streams go to (``REDIS_URL`` + ``REDIS_PASSWORD``).

    Opened only while async sub-agents are on.
    """

    model_config = _BASE_MODEL_CONFIG

    url: str = Field("redis://redis:6379/0", validation_alias="REDIS_URL")
    password: SecretStr = Field(default_factory=lambda: SecretStr(""))

    @field_validator("password", mode="before")
    @classmethod
    def _load_password(cls, value: object) -> object:
        return _secret_or_file(value, "REDIS_PASSWORD")


class LangfuseSettings(BaseSettings):
    """Agent traces to the self-hosted Langfuse: off unless the URL and both keys are set.

    A run never waits on it: spans leave in a background batch, and a Langfuse
    that is down only costs those traces.
    """

    model_config = _BASE_MODEL_CONFIG

    base_url: str = Field("", validation_alias="LANGFUSE_BASE_URL")
    public_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    secret_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    sample_rate: float = Field(1.0, ge=0.0, le=1.0, validation_alias="LANGFUSE_SAMPLE_RATE")
    timeout_seconds: int = Field(5, ge=1, le=30, validation_alias="LANGFUSE_TIMEOUT_SECONDS")

    @field_validator("public_key", mode="before")
    @classmethod
    def _load_public_key(cls, value: object) -> object:
        return _secret_or_file(value, "LANGFUSE_PUBLIC_KEY")

    @field_validator("secret_key", mode="before")
    @classmethod
    def _load_secret_key(cls, value: object) -> object:
        return _secret_or_file(value, "LANGFUSE_SECRET_KEY")

    @property
    def enabled(self) -> bool:
        """True when the URL and both keys are set: the one "is tracing on" check."""
        return bool(
            self.base_url.strip()
            and self.public_key.get_secret_value()
            and self.secret_key.get_secret_value()
        )


class AsyncTasksSettings(BaseSettings):
    """Async sub-agents: every sub-agent runs as a background task.

    ``ASYNC_SUBAGENTS_ENABLED=false`` falls back to the blocking ``task`` tool.
    The caps fail closed: a refused start is a tool error the model reads.
    """

    model_config = _BASE_MODEL_CONFIG

    enabled: bool = Field(True, validation_alias="ASYNC_SUBAGENTS_ENABLED")
    max_active_per_user: int = Field(
        16, ge=1, le=1000, validation_alias="ASYNC_TASKS_MAX_ACTIVE_PER_USER"
    )
    max_children_per_task: int = Field(
        8, ge=1, le=100, validation_alias="ASYNC_TASKS_MAX_CHILDREN_PER_TASK"
    )
    run_timeout_seconds: int = Field(
        1800, ge=10, le=86400, validation_alias="ASYNC_TASKS_RUN_TIMEOUT_SECONDS"
    )
    max_runs_per_task: int = Field(
        50, ge=1, le=1000, validation_alias="ASYNC_TASKS_MAX_RUNS_PER_TASK"
    )
    launch_token_ttl_seconds: int = Field(
        7200, ge=60, le=86400, validation_alias="ASYNC_TASKS_LAUNCH_TOKEN_TTL_SECONDS"
    )
    # HMAC key of the launch token. Empty = derived from INTERNAL_SERVICE_SECRET.
    launch_secret: SecretStr = Field(default_factory=lambda: SecretStr(""))
    # The Agent Protocol base URL the middleware is given. Requests never leave
    # the process (an in-process ASGI transport serves them).
    self_url: str = Field("http://agents.internal", validation_alias="ASYNC_TASKS_SELF_URL")
    events_maxlen: int = Field(20000, ge=100, validation_alias="ASYNC_TASKS_EVENTS_MAXLEN")
    events_ttl_seconds: int = Field(3600, ge=60, validation_alias="ASYNC_TASKS_EVENTS_TTL_SECONDS")
    streams_maxlen: int = Field(10000, ge=100, validation_alias="ASYNC_TASKS_STREAMS_MAXLEN")
    result_preview_chars: int = Field(
        2000, ge=100, le=2000, validation_alias="ASYNC_TASKS_RESULT_PREVIEW_CHARS"
    )

    @field_validator("launch_secret", mode="before")
    @classmethod
    def _load_launch_secret(cls, value: object) -> object:
        return _secret_or_file(value, "ASYNC_TASKS_LAUNCH_SECRET")


class Settings(BaseSettings):
    model_config = _BASE_MODEL_CONFIG

    app: AppSettings = Field(default_factory=AppSettings)
    api_keys: ApiKeysSettings = Field(default_factory=ApiKeysSettings)
    gemini: GeminiSettings = Field(default_factory=GeminiSettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)
    tls: TlsSettings = Field(default_factory=TlsSettings)
    checkpointer: CheckpointerSettings = Field(default_factory=CheckpointerSettings)
    proxy: ProxySettings = Field(default_factory=ProxySettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    registry: AgentRegistrySettings = Field(default_factory=AgentRegistrySettings)
    model_profiles: ModelProfileSettings = Field(default_factory=ModelProfileSettings)
    filesystem: FilesystemSettings = Field(default_factory=FilesystemSettings)
    conversation_files: ConversationFilesSettings = Field(default_factory=ConversationFilesSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    summarization: SummarizationSettings = Field(default_factory=SummarizationSettings)
    rate_limit_retry: RateLimitRetrySettings = Field(default_factory=RateLimitRetrySettings)
    agui: AguiSettings = Field(default_factory=AguiSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    async_tasks: AsyncTasksSettings = Field(default_factory=AsyncTasksSettings)
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)

    @model_validator(mode="after")
    def _require_internal_secret(self) -> Settings:
        """Fail closed: a deployed service never accepts unauthenticated callers."""
        if not self.app.is_local and not self.proxy.internal_service_secret.get_secret_value():
            raise ValueError(
                f"INTERNAL_SERVICE_SECRET must be set when APP_ENV={self.app.env!r}; "
                "refusing to start without an internal-caller secret."
            )
        return self

    @model_validator(mode="after")
    def _harden_redaction_secret(self) -> Settings:
        """The shared default is reversible by anyone who reads the source, so an
        unset secret becomes a random per-process key instead: hashes stay
        one-way, at the cost of cross-restart correlation."""
        if self.logging.redaction_secret.get_secret_value() == _DEFAULT_REDACTION_SECRET:
            self.logging.redaction_secret = SecretStr(secrets.token_hex(32))
        return self


settings = Settings()
