"""Request trust: the internal-caller secret every route requires."""

from core.security.internal_trust import (
    INTERNAL_SECRET_HEADER,
    internal_service_headers,
    is_internal_caller,
    require_internal_caller,
)

__all__ = [
    "INTERNAL_SECRET_HEADER",
    "internal_service_headers",
    "is_internal_caller",
    "require_internal_caller",
]
