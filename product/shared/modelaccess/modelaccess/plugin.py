"""The ``access`` block of a plugin.yaml, normalised.

```yaml
access:
  type: mlflow_model | rest | llm_chat | pickle
  uri: models:/sys-002-credit-scorer@champion      # mlflow_model (local MLflow)
  url: http://model-gateway:8000/v1/...  # rest / llm_chat; a path joins MODEL_GATEWAY_URL
  auth: {type: bearer, secret_ref: env://MODEL_GATEWAY_TOKEN}   # a reference, never the secret
  limits: {rps: 5, max_requests: 500, timeout_s: 10}
  batch_size: 100                                  # rest only
  request: {messages: [...]}                       # llm_chat: request shape
  response: {reply_field: reply}                   # llm_chat: where the reply is
```

Secrets are only ever *named*: ``secret_ref: env://NAME`` (or a bare ``NAME``) or the
older ``auth.token_env``. Anything else (``vault://...``) is refused here, because only
the sandbox runner's environment may hold credentials.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

ACCESS_TYPES = ("mlflow_model", "rest", "llm_chat", "pickle")
DEFAULT_TOKEN_ENV = "MODEL_GATEWAY_TOKEN"  # noqa: S105 - an env var name, not a secret
DEFAULT_GATEWAY_URL = "http://model-gateway:8000"


class AccessError(ValueError):
    """The plugin's access block is invalid or names an unsupported source."""


def secret_env_name(auth: dict | None) -> str:
    """The env var that holds the bearer token (never the token itself)."""
    auth = auth or {}
    ref = auth.get("secret_ref")
    if ref:
        ref = str(ref)
        if ref.startswith("env://"):
            return ref.removeprefix("env://")
        if "://" in ref:
            raise AccessError(
                f"secret_ref {ref!r}: only env://NAME is supported (the runner's environment)"
            )
        return ref
    return str(auth.get("token_env") or DEFAULT_TOKEN_ENV)


def resolve_url(url: str) -> str:
    """A path (``/v1/...``) is joined to ``MODEL_GATEWAY_URL``."""
    if url.startswith("/"):
        base = os.environ.get("MODEL_GATEWAY_URL", DEFAULT_GATEWAY_URL)
        return base.rstrip("/") + url
    return url


@dataclass(slots=True)
class AccessConfig:
    type: str
    uri: str = ""
    url: str = ""
    token_env: str = DEFAULT_TOKEN_ENV
    rps: float = 0.0
    max_requests: int = 0
    timeout_s: float = 30.0
    batch_size: int = 100
    environment: str = ""
    response: dict[str, Any] = field(default_factory=dict)

    def token(self) -> str:
        return os.environ.get(self.token_env, "")


def access_config(plugin: dict, *, override_type: str | None = None) -> AccessConfig:
    """Read and validate ``plugin['access']``."""
    access = (plugin or {}).get("access") or {}
    kind = override_type or access.get("type") or ""
    if kind not in ACCESS_TYPES:
        raise AccessError(f"access.type {kind!r} is not supported ({', '.join(ACCESS_TYPES)})")
    limits = access.get("limits") or {}
    return AccessConfig(
        type=kind,
        uri=str(access.get("uri") or ""),
        url=resolve_url(str(access.get("url") or "")),
        token_env=secret_env_name(access.get("auth")),
        rps=float(limits.get("rps") or 0),
        max_requests=int(limits.get("max_requests") or 0),
        timeout_s=float(limits.get("timeout_s") or 30),
        batch_size=int(access.get("batch_size") or 100),
        environment=str(access.get("environment") or ""),
        response=dict(access.get("response") or {}),
    )
