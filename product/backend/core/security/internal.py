"""The internal API's guard: the agents service proves itself with a shared secret.

The secret is ``AGENTS_SERVICE_SECRET`` (the same value the backend sends to
the agents service as ``X-Internal-Service-Secret``). The agents service sends
it back as ``X-Internal-Secret`` (``X-Internal-Service-Secret`` is accepted
too). With no secret configured the internal API is open only in
development/test; anywhere else it is refused.
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, status

from core.logging import get_logger
from core.settings import settings

logger = get_logger(__name__)

INTERNAL_SECRET_HEADERS = ("X-Internal-Secret", "X-Internal-Service-Secret")
_OPEN_WHEN_UNSET_ENVS = frozenset({"development", "test"})


async def require_internal_secret(request: Request) -> None:
    """FastAPI dependency: 401 unless the request carries the shared secret."""
    expected = settings.upstream.agents_service_secret.get_secret_value()
    if not expected:
        if settings.app.env in _OPEN_WHEN_UNSET_ENVS:
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal API disabled: AGENTS_SERVICE_SECRET is not set.",
        )
    for header in INTERNAL_SECRET_HEADERS:
        given = request.headers.get(header)
        if given and hmac.compare_digest(given.encode(), expected.encode()):
            return
    logger.warning("internal_auth_failed", "Internal API call without a valid secret")
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal secret.")
