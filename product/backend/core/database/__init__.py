"""The SQL data layer: engine/session wiring and ORM models.

Re-exports ``engine`` and ``models`` so callers use ``from core.database import ...``.
"""

from core.database.engine import (
    Base,
    SessionLocal,
    _build_pg_ssl_context,
    b64_decode,
    b64_encode,
    engine,
    gen_uuid,
    get_db,
)
from core.database.models import (
    TASK_SETTLED_STATUSES,
    AttachmentTable,
    BlobTable,
    ConversationTable,
    ConversationTaskTable,
    MessageKindEnum,
    MessageSenderEnum,
    MessageTable,
)

__all__ = [
    "TASK_SETTLED_STATUSES",
    "AttachmentTable",
    "Base",
    "BlobTable",
    "ConversationTable",
    "ConversationTaskTable",
    "MessageKindEnum",
    "MessageSenderEnum",
    "MessageTable",
    "SessionLocal",
    "_build_pg_ssl_context",
    "b64_decode",
    "b64_encode",
    "engine",
    "gen_uuid",
    "get_db",
]
