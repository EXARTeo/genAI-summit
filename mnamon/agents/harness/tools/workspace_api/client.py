"""HTTP access the chat copilot's tools use: the backend's systems/audits API and reg-memory.

Deterministic plumbing, no model. The backend calls go to its public ``/v1``
routes with the run's ``X-Client-Id`` (systems and audits are not scoped by
client id, and the client id is the actor of every write, so a proposed note is
attributed to the engineer's browser, as if they had typed it). reg-memory is
read with its internal secret. Every client takes an optional
``httpx.AsyncClient`` so the tests inject a ``MockTransport``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from core.settings import settings

#: A test seam: tests swap in an ``httpx.MockTransport``.
transport: httpx.AsyncBaseTransport | None = None


class WorkspaceAPIError(RuntimeError):
    """A dependency answered with an error; ``public`` is safe to show the model."""

    def __init__(self, service: str, status: int | None, detail: str = "") -> None:
        super().__init__(f"{service}: {status} {detail}")
        self.status = status
        self.public = f"{service} answered {status}" if status else f"{service} is unreachable"


async def _request(
    client: httpx.AsyncClient | None, service: str, method: str, url: str, **kwargs: Any
) -> Any:
    """One call; a short-lived client unless the caller injected one (tests)."""
    try:
        if client is not None:
            response = await client.request(method, url, **kwargs)
        else:
            timeout = settings.pipeline.http_timeout_seconds
            async with httpx.AsyncClient(timeout=timeout, transport=transport) as own:
                response = await own.request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        raise WorkspaceAPIError(service, None, type(exc).__name__) from exc
    if response.status_code >= 400:
        raise WorkspaceAPIError(service, response.status_code, response.text[:300])
    return response.json() if response.content else None


class WorkspaceAPI:
    """The backend (``/v1/systems``, ``/v1/audits``) and reg-memory, for one run's client."""

    def __init__(
        self,
        *,
        client_id: str,
        agent_slug: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.client = client
        self.backend = settings.pipeline.backend_internal_url.rstrip("/")
        self.regmem = settings.pipeline.reg_memory_url.rstrip("/")
        self.backend_headers = {"X-Client-Id": client_id, "X-Agent-Name": agent_slug}
        self.regmem_headers = {
            "X-Internal-Secret": settings.pipeline.reg_memory_secret.get_secret_value()
        }
        self._kb_version: str | None = None

    async def _backend(self, method: str, path: str, **kwargs: Any) -> Any:
        return await _request(
            self.client,
            "backend",
            method,
            f"{self.backend}/v1{path}",
            headers=self.backend_headers,
            **kwargs,
        )

    async def _regmem(self, path: str, **params: Any) -> Any:
        clean = {k: v for k, v in params.items() if v is not None}
        return await _request(
            self.client,
            "reg-memory",
            "GET",
            f"{self.regmem}{path}",
            headers=self.regmem_headers,
            params=clean or None,
        )

    # -- systems ----------------------------------------------------------------
    async def systems(self) -> list[dict[str, Any]]:
        body = await self._backend("GET", "/systems")
        return list(body or [])

    async def system(self, system_id: str) -> dict[str, Any]:
        return await self._backend("GET", f"/systems/{quote(system_id, safe='')}")

    async def tree(self, system_id: str, prefix: str | None = None) -> list[dict[str, Any]]:
        params = {"prefix": prefix} if prefix else None
        body = await self._backend(
            "GET", f"/systems/{quote(system_id, safe='')}/files", params=params
        )
        return list(body or [])

    async def read(self, system_id: str, path: str) -> dict[str, Any]:
        return await self._backend(
            "GET",
            f"/systems/{quote(system_id, safe='')}/files/{quote(path)}",
            params={"format": "json"},
        )

    async def write(
        self, system_id: str, path: str, content: str, *, reason: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._backend(
            "PUT",
            f"/systems/{quote(system_id, safe='')}/files/{quote(path)}",
            json={
                "content": content,
                "contentType": "text/markdown",
                "reason": reason,
                "data": data,
            },
        )

    # -- audits -----------------------------------------------------------------
    async def audits(self, system_id: str | None = None) -> list[dict[str, Any]]:
        params = {"systemId": system_id} if system_id else None
        return list(await self._backend("GET", "/audits", params=params) or [])

    async def audit(self, audit_id: str) -> dict[str, Any]:
        return await self._backend("GET", f"/audits/{quote(audit_id, safe='')}")

    async def artifact(self, audit_id: str, artifact_id: str) -> dict[str, Any]:
        return await self._backend(
            "GET",
            f"/audits/{quote(audit_id, safe='')}/artifacts/{quote(artifact_id, safe='')}",
        )

    async def start_audit(self, system_id: str) -> dict[str, Any]:
        return await self._backend(
            "POST", f"/systems/{quote(system_id, safe='')}/audits", json={"data": {}}
        )

    # -- regulation -------------------------------------------------------------
    async def kb_version(self) -> str | None:
        """The active release, read once per run so every lookup is pinned to it."""
        if self._kb_version is None:
            body = await self._regmem("/v1/releases")
            active = body.get("active") if isinstance(body, dict) else None
            self._kb_version = active if isinstance(active, str) else None
        return self._kb_version

    async def provision(self, provision_id: str) -> dict[str, Any]:
        kb = await self.kb_version()
        return await self._regmem(f"/v1/provisions/{quote(provision_id)}", kb_version=kb)

    async def search(self, query: str) -> list[dict[str, Any]]:
        kb = await self.kb_version()
        body = await self._regmem(
            "/v1/provisions", q=query, kb_version=kb, limit=10, with_text=False
        )
        return list(body.get("items") or []) if isinstance(body, dict) else []


__all__ = ["WorkspaceAPI", "WorkspaceAPIError"]
