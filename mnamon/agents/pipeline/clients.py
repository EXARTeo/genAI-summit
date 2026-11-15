"""HTTP clients the pipelines use: the backend's internal API, reg-memory, the sandbox runner.

Deterministic plumbing only; no model is called here. Every client takes an
optional ``httpx.AsyncClient`` so the tests inject a ``MockTransport``.

* :class:`BackendInternal`: ``/internal/audits/{id}`` (read the audit and its
  system's files, write artifacts, move the stage) and the impact routes.
* :class:`RegMemory`: requirements, provisions, interpretations, releases, changes.
* :class:`SandboxRunner`: one ``POST /v1/exec`` per call with the files the
  command needs in ``input/`` (the runner contract in ``docs/services/sandbox.md``;
  same secret and identity rules as the deep agents' ``execute``).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from core.settings import settings
from harness.filesystem.sandbox_backend import EXEC_PATH, RUNNER_SECRET_HEADER

#: Extra attempts of a GET whose connection failed (busy backend, a restart).
TRANSPORT_RETRIES = 2

#: The agent name the pipeline writes under (``agent:<name>`` in the backend's ledger).
PIPELINE_AGENT = "audit-pipeline"


class PipelineHTTPError(RuntimeError):
    """A dependency answered with an error; ``public`` is safe to show."""

    def __init__(self, service: str, status: int | None, detail: str) -> None:
        super().__init__(f"{service}: {status} {detail}")
        self.service = service
        self.status = status
        self.public = f"{service} answered {status}" if status else f"{service} is unreachable"
        self.public_message = f"A pipeline dependency failed: {self.public}."


def _client(client: httpx.AsyncClient | None) -> httpx.AsyncClient:
    return client or httpx.AsyncClient(timeout=settings.pipeline.http_timeout_seconds)


async def _json(
    client: httpx.AsyncClient, service: str, method: str, url: str, **kwargs: Any
) -> Any:
    # A dropped connection on a read (GET) is retried; a write is never sent twice.
    attempts = TRANSPORT_RETRIES + 1 if method == "GET" else 1
    for attempt in range(1, attempts + 1):
        try:
            response = await client.request(method, url, **kwargs)
            break
        except httpx.HTTPError as exc:
            if attempt >= attempts:
                raise PipelineHTTPError(service, None, type(exc).__name__) from exc
            await asyncio.sleep(0.5 * attempt)
    if response.status_code >= 400:
        raise PipelineHTTPError(service, response.status_code, response.text[:300])
    return response.json() if response.content else None


class BackendInternal:
    """The backend's internal API, scoped to one audit (``/internal/audits/{id}``)."""

    def __init__(
        self,
        audit_id: str,
        *,
        run_id: str | None = None,
        trace_id: str | None = None,
        agent: str = PIPELINE_AGENT,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.audit_id = audit_id
        self.base = settings.pipeline.backend_internal_url.rstrip("/")
        self.client = _client(client)
        secret = settings.proxy.internal_service_secret.get_secret_value()
        self.headers = {"X-Internal-Secret": secret, "X-Agent-Name": agent}
        if run_id:
            self.headers["X-Run-Id"] = run_id
        if trace_id:
            self.headers["X-Trace-Id"] = trace_id

    @property
    def _root(self) -> str:
        return f"{self.base}/internal/audits/{quote(self.audit_id, safe='')}"

    async def _call(self, method: str, path: str = "", **kwargs: Any) -> Any:
        return await _json(
            self.client, "backend", method, f"{self._root}{path}", headers=self.headers, **kwargs
        )

    async def audit(self) -> dict[str, Any]:
        """``{audit (artifacts, approvals), system}``."""
        return await self._call("GET")

    async def patch(
        self,
        *,
        stage: str | None = None,
        status: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if stage is not None:
            body["stage"] = stage
        if status is not None:
            body["status"] = status
        if data is not None:
            body["data"] = dict(data)
        return await self._call("PATCH", json=body)

    async def tree(self, prefix: str | None = None) -> list[dict[str, Any]]:
        return await self._call("GET", "/files", params={"prefix": prefix} if prefix else None)

    async def read(self, path: str) -> str | None:
        """A file's text (``None`` for a binary file)."""
        body = await self._call("GET", f"/files/{quote(path)}")
        return body.get("text") if isinstance(body, dict) else None

    async def write_artifact(
        self,
        kind: str,
        data: Mapping[str, Any],
        *,
        name: str = "main",
        file_refs: list[Any] | None = None,
        status: str = "proposed",
    ) -> dict[str, Any]:
        return await self._call(
            "POST",
            "/artifacts",
            json={
                "kind": kind,
                "name": name,
                "data": dict(data),
                "fileRefs": file_refs or [],
                "status": status,
            },
        )

    async def seal_finding(self, finding: Mapping[str, Any]) -> dict[str, Any]:
        """``POST /internal/audits/{id}/findings``: one sealed finding (append-only)."""
        return await self._call("POST", "/findings", json=dict(finding))

    async def register(self) -> dict[str, Any]:
        """``GET /internal/audits/{id}/register``: the system's findings register."""
        return await self._call("GET", "/register")


class BackendImpact:
    """The backend's cross-system internal routes the impact pipeline needs."""

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self.base = settings.pipeline.backend_internal_url.rstrip("/")
        self.client = _client(client)
        secret = settings.proxy.internal_service_secret.get_secret_value()
        self.headers = {"X-Internal-Secret": secret, "X-Agent-Name": "change-judge"}

    async def impact_index(self) -> list[dict[str, Any]]:
        """Every system with its latest audit's live findings and test results."""
        return await _json(
            self.client,
            "backend",
            "GET",
            f"{self.base}/internal/impact-index",
            headers=self.headers,
        )

    async def start_audit(self, system_id: str, data: Mapping[str, Any]) -> dict[str, Any]:
        """A new audit of ``system_id`` (the backend starts its pipeline)."""
        return await _json(
            self.client,
            "backend",
            "POST",
            f"{self.base}/internal/systems/{quote(system_id, safe='')}/audits",
            headers=self.headers,
            json={"stage": "load_context", "data": dict(data)},
        )

    async def store_judgement(
        self, change_id: str, affected: list[dict[str, Any]], decided_by: str
    ) -> Any:
        """Write the per-system judgements onto the backend's ``regulation_changes`` row."""
        return await _json(
            self.client,
            "backend",
            "PUT",
            f"{self.base}/internal/regulation/changes/{quote(change_id, safe='')}/judgement",
            headers=self.headers,
            json={"affected": affected, "decidedBy": decided_by},
        )


class RegMemory:
    """reg-memory (RKS): the regulation, pinned by ``kb_version`` where it matters."""

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self.base = settings.pipeline.reg_memory_url.rstrip("/")
        self.client = _client(client)
        self.headers = {"X-Internal-Secret": settings.pipeline.reg_memory_secret.get_secret_value()}

    async def _get(self, path: str, **params: Any) -> Any:
        clean = {k: v for k, v in params.items() if v is not None}
        return await _json(
            self.client,
            "reg-memory",
            "GET",
            f"{self.base}{path}",
            headers=self.headers,
            params=clean or None,
        )

    async def active_kb_version(self) -> str | None:
        """The active release (``GET /v1/releases`` -> ``{active, items}``)."""
        body = await self._get("/v1/releases")
        return body.get("active") if isinstance(body, dict) else None

    async def requirements(self, **params: Any) -> dict[str, Any]:
        """``{kb_version, query, total, items}``: the applicability query of ``load_context``."""
        return await self._get("/v1/requirements", **params)

    async def test_templates(self, kb_version: str | None = None) -> list[dict[str, Any]]:
        body = await self._get("/v1/test-templates", kb_version=kb_version)
        return list(body.get("items") or []) if isinstance(body, dict) else []

    async def provision(self, provision_id: str, kb_version: str | None = None) -> dict[str, Any]:
        return await self._get(f"/v1/provisions/{quote(provision_id)}", kb_version=kb_version)

    async def search_provisions(self, **params: Any) -> list[dict[str, Any]]:
        body = await self._get("/v1/provisions", **params)
        return list(body.get("items") or []) if isinstance(body, dict) else []

    async def search(
        self, q: str, kb_version: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        """``GET /v1/provisions/search``: ranked hits (id, label, title, snippet, score)."""
        body = await self._get("/v1/provisions/search", q=q, kb_version=kb_version, limit=limit)
        return list(body.get("items") or []) if isinstance(body, dict) else []

    async def interpretation(
        self, interpretation_id: str, kb_version: str | None = None
    ) -> dict[str, Any]:
        """``GET /v1/interpretations/{id}``: one guidance node with its full text."""
        return await self._get(
            f"/v1/interpretations/{quote(interpretation_id)}", kb_version=kb_version
        )

    async def interpretations(
        self, relates_to: str, kb_version: str | None = None
    ) -> list[dict[str, Any]]:
        body = await self._get("/v1/interpretations", relates_to=relates_to, kb_version=kb_version)
        return list(body.get("items") or []) if isinstance(body, dict) else []

    async def change(self, change_id: str) -> dict[str, Any]:
        return await self._get(f"/v1/changes/{quote(change_id)}")


@dataclass
class ExecResult:
    """One sandbox call: exit code, output, the files it wrote under ``output/``."""

    exit_code: int | None
    stdout: str
    stderr: str
    killed_reason: str | None = None
    duration_ms: int | None = None
    files: dict[str, bytes] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def text(self, name: str) -> str | None:
        data = self.files.get(name)
        return data.decode("utf-8", errors="replace") if data is not None else None

    def summary(self, limit: int = 1500) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "killed_reason": self.killed_reason,
            "duration_ms": self.duration_ms,
            "stdout_tail": self.stdout[-limit:],
            "stderr_tail": self.stderr[-limit:],
            "files": sorted(self.files),
        }


class SandboxRunner:
    """``POST /v1/exec`` on the sandbox runner (synthkit is installed there)."""

    def __init__(self, *, user: str, conversation: str, client: httpx.AsyncClient | None = None):
        fs = settings.filesystem
        self.url = fs.sandbox_runner_url.rstrip("/")
        self.secret = fs.sandbox_runner_secret.get_secret_value()
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                settings.pipeline.sandbox_timeout_seconds + 30,
                connect=fs.sandbox_runner_connect_timeout_seconds,
            )
        )
        key = settings.logging.redaction_secret.get_secret_value().encode()
        # The runner keeps an audit record keyed by a hash, never the raw id.
        self.user = hmac.new(key, user.encode(), hashlib.sha256).hexdigest()[:32]
        self.conversation = _safe_id(conversation)

    @property
    def available(self) -> bool:
        return bool(self.url)

    async def run(
        self, command: str, files: Mapping[str, str | bytes], *, timeout: int | None = None
    ) -> ExecResult:
        """Run ``command`` in ``output/`` with ``files`` (``input/<rel>``: text or bytes)."""
        if not self.url:
            raise PipelineHTTPError("sandbox", None, "SANDBOX_RUNNER_URL is not set")
        payload = {
            "user_id": self.user,
            "agent_slug": PIPELINE_AGENT,
            "conversation_id": self.conversation,
            "command": command,
            "timeout_seconds": timeout or settings.pipeline.sandbox_timeout_seconds,
            "workdir": "output",
            "files": [
                {
                    "path": f"input/{path}",
                    "content_b64": base64.b64encode(
                        body.encode("utf-8") if isinstance(body, str) else body
                    ).decode("ascii"),
                }
                for path, body in files.items()
            ],
        }
        body = await _json(
            self.client,
            "sandbox",
            "POST",
            f"{self.url}{EXEC_PATH}",
            headers={RUNNER_SECRET_HEADER: self.secret},
            json=payload,
        )
        returned: dict[str, bytes] = {}
        for item in body.get("files") or []:
            path = str(item.get("path") or "")
            rel = path.split("output/", 1)[1] if "output/" in path else path
            try:
                returned[rel] = base64.b64decode(item.get("content_b64") or "")
            except (ValueError, TypeError):
                continue
        return ExecResult(
            exit_code=body.get("exit_code"),
            stdout=str(body.get("stdout") or ""),
            stderr=str(body.get("stderr") or ""),
            killed_reason=body.get("killed_reason"),
            duration_ms=body.get("duration_ms"),
            files=returned,
        )


def _safe_id(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "_-" else "-" for ch in value).strip("-")
    return (cleaned or "audit")[:128]


__all__ = [
    "PIPELINE_AGENT",
    "BackendImpact",
    "BackendInternal",
    "ExecResult",
    "PipelineHTTPError",
    "RegMemory",
    "SandboxRunner",
]
