"""Attachment DTOs: the upload input, the attachment as a message carries it, and
the rows of the image gallery.

Uploads arrive as base64 in the JSON body. Every cheap check (MIME shape,
declared size, encoded length) runs before the payload is decoded, so an
oversized or malformed upload is refused without ever allocating its bytes.
"""

import base64
import binascii
import math
import re

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)

from core.settings import settings
from schema.base import UTCDateTime

#: ``type/subtype`` per RFC 6838 (restricted names), no parameters.
_MIME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}$")
MAX_FILE_NAME_LENGTH = 255


def max_encoded_length(raw_bytes: int) -> int:
    """The longest base64 string (padded) that can decode to ``raw_bytes`` bytes."""
    return 4 * math.ceil(raw_bytes / 3)


def _megabytes(value: int) -> int:
    return value // (1024 * 1024)


class BlobOut(BaseModel):
    """A blob's bytes, read only to inline an image as base64; never serialized."""

    model_config = ConfigDict(from_attributes=True)
    data: bytes


class AttachmentOut(BaseModel):
    """An attachment as the UI reads it. Images carry their bytes as base64
    (``data``); every other file is fetched through the download/preview routes."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    name: str = Field(..., validation_alias="file_name")
    mime: str = Field(..., validation_alias="mime_type")
    size: int | None = Field(None, validation_alias="size_bytes")
    timestamp: UTCDateTime = Field(..., validation_alias="created_at")
    # "upload" for user files, "generated" for a file the agent produced (which
    # also carries the agent's title and summary).
    origin: str = Field("upload", validation_alias="origin")
    title: str | None = Field(None, validation_alias="title")
    summary: str | None = Field(None, validation_alias="summary")

    # Read from the ORM relation to inline images; excluded from the output.
    blob: BlobOut | None = Field(None, validation_alias="blob", exclude=True)
    blobId: str | None = Field(None, validation_alias="blob_id")

    # Base64 bytes, for images only.
    data: str | None = None

    @model_validator(mode="after")
    def _inject_image_b64(self) -> "AttachmentOut":
        if self.mime and self.mime.startswith("image/") and self.blob and self.blob.data:
            self.data = base64.b64encode(self.blob.data).decode("ascii")
        self.blob = None
        return self


class AttachmentIn(BaseModel):
    """One uploaded file, base64-encoded. ``size`` is optional and, when given,
    must match the decoded length."""

    name: str = Field(..., max_length=MAX_FILE_NAME_LENGTH)
    mime: str = Field(..., max_length=255)
    dataB64: str
    size: int | None = Field(None, ge=0)

    _raw: bytes = PrivateAttr(default=b"")

    @field_validator("name", "mime", "dataB64", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("mime", mode="after")
    @classmethod
    def _normalize_mime(cls, value: str) -> str:
        return value.lower()

    @model_validator(mode="after")
    def _validate_attachment(self) -> "AttachmentIn":
        limit = settings.attachments.max_size_bytes
        if not self.name:
            raise ValueError("Attachment name is required.")
        if not self.mime:
            raise ValueError(f"Attachment '{self.name}' is missing a MIME type.")
        if not _MIME_PATTERN.fullmatch(self.mime):
            raise ValueError(f"Attachment '{self.name}' has an invalid MIME type.")
        if not self.dataB64:
            raise ValueError(f"Attachment '{self.name}' is missing data.")
        # Size limits on the declared size and the encoded length come first:
        # nothing is decoded for a payload that cannot fit.
        if (self.size is not None and self.size > limit) or len(self.dataB64) > max_encoded_length(
            limit
        ):
            raise ValueError(f"Attachment '{self.name}' exceeds the {_megabytes(limit)} MB limit.")
        try:
            raw = base64.b64decode(self.dataB64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"Attachment '{self.name}' is not valid base64.") from exc
        if not raw:
            raise ValueError(f"Attachment '{self.name}' is empty.")
        if len(raw) > limit:
            raise ValueError(f"Attachment '{self.name}' exceeds the {_megabytes(limit)} MB limit.")
        if self.size is not None and self.size != len(raw):
            raise ValueError(f"Attachment '{self.name}' size metadata does not match payload size.")
        self.size = len(raw)
        self._raw = raw
        return self

    def raw_bytes(self) -> bytes:
        """The decoded payload (decoded once, during validation)."""
        return self._raw or base64.b64decode(self.dataB64, validate=True)


def check_attachment_batch(items: object) -> object:
    """Count and total-size limits for one message's uploads, on the raw request
    data, before any attachment is validated or decoded."""
    if not isinstance(items, list):
        return items
    cap = settings.attachments.max_per_message
    if len(items) > cap:
        raise ValueError(f"No more than {cap} attachments are allowed per message.")
    encoded_total = sum(
        len(item.get("dataB64") or "")
        for item in items
        if isinstance(item, dict) and isinstance(item.get("dataB64"), str)
    )
    total_limit = settings.attachments.max_total_bytes
    if encoded_total > max_encoded_length(total_limit):
        raise ValueError(
            f"Total attachment payload exceeds the {_megabytes(total_limit)} MB limit."
        )
    return items


class ImageOut(BaseModel):
    """One image in the caller's gallery, with its bytes as base64."""

    blobId: str = Field(..., validation_alias="blob_id")
    attachmentId: str = Field(..., validation_alias="attachment_id")
    conversationId: str = Field(..., validation_alias="conversation_id")
    messageId: str = Field(..., validation_alias="message_id")
    fileName: str = Field(..., validation_alias="file_name")
    mime: str = Field(..., validation_alias="mime_type")
    createdAt: UTCDateTime = Field(..., validation_alias="created_at")
    dataB64: str
