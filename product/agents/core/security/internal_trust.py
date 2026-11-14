"""The internal-caller gate: every route but ``/health`` needs the shared secret.

The backend sends ``X-Internal-Service-Secret`` (its ``AGENTS_SERVICE_SECRET``)
on every run request, and the in-process async-task transport sends it too.
With no secret configured (development and test only; settings refuse to start
without one anywhere else) every caller is accepted.
"""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, status

from core.settings import settings

INTERNAL_SECRET_HEADER = "X-Internal-Service-Secret"  # noqa: S105 - a header name


def is_internal_caller(request: Request) -> bool:
    """True when the request carries the secret, or when none is configured."""
    expected = settings.proxy.internal_service_secret.get_secret_value()
    if not expected:
        return True
    presented = request.headers.get(INTERNAL_SECRET_HEADER, "")
    return bool(presented) and secrets.compare_digest(presented, expected)


def require_internal_caller(request: Request) -> None:
    """FastAPI dependency: 403 for a caller without the secret."""
    if not is_internal_caller(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


def internal_service_headers() -> dict[str, str]:
    """The headers of an internal call back into this service (async tasks)."""
    secret = settings.proxy.internal_service_secret.get_secret_value()
    return {INTERNAL_SECRET_HEADER: secret} if secret else {}
