"""A polite JSON client for a model endpoint (``rest`` / ``llm_chat`` targets).

Bearer token from the env var the plugin names, ``limits.rps`` pacing, a hard
``max_requests`` budget, and 429 retried after ``Retry-After`` (capped at 30 s).
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from modelaccess.plugin import AccessConfig


class EndpointError(RuntimeError):
    """The endpoint failed in a way the caller cannot use (budget, 429 storm, transport)."""


class RestClient:
    def __init__(
        self, config: AccessConfig, *, url: str | None = None, transport=None, retries: int = 4
    ):
        self.url = url or config.url
        if not self.url:
            raise EndpointError(f"{config.type} access needs access.url")
        self.rps = config.rps
        self.max_requests = config.max_requests
        self.retries = retries
        token = config.token()
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.client = httpx.Client(timeout=config.timeout_s, transport=transport)
        self.sent = 0
        self._last = 0.0

    def _pace(self) -> None:
        if self.max_requests and self.sent >= self.max_requests:
            raise EndpointError(f"max_requests ({self.max_requests}) reached")
        if self.rps > 0:
            wait = self._last + 1.0 / self.rps - time.monotonic()
            if wait > 0:
                time.sleep(wait)
        self._last = time.monotonic()
        self.sent += 1

    def post(self, payload: Any) -> httpx.Response:
        """POST JSON; returns the final response (any status except a persistent 429)."""
        for _attempt in range(self.retries):
            self._pace()
            try:
                resp = self.client.post(self.url, json=payload, headers=self.headers)
            except httpx.HTTPError as exc:
                raise EndpointError(f"{type(exc).__name__}: {exc}") from exc
            if resp.status_code == 429:
                time.sleep(min(float(resp.headers.get("Retry-After", "1")), 30.0))
                continue
            return resp
        raise EndpointError("rate limited (429) after retries")
