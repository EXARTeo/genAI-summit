"""Attachment routes (``/v1/attachments``): streamed download, inline preview
and the caller's image gallery.

Files are only reachable through a conversation the caller owns (404
otherwise). Downloads are always ``attachment`` + ``nosniff``; previews are
sandboxed and never inline an image or active content. Office documents
(docx, xlsx, pptx) are previewed through the same inline route and rendered
by the UI; there is no public, token-based viewer link.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from fastapi_pagination import Page, Params
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.logging import get_logger
from core.security.client import Caller, get_caller
from core.security.rate_limit import conversation_rate_limit
from schema.attachments import ImageOut
from utils.attachments import list_client_images, stream_blob_response

router = APIRouter()
logger = get_logger(__name__)


@router.get(
    "/images",
    response_model=Page[ImageOut],
    summary="List the caller's images, newest first, with their bytes as base64",
)
async def list_images(
    caller: Annotated[Caller, Depends(get_caller)],
    _rate_limited: Annotated[None, Depends(conversation_rate_limit)],
    params: Annotated[Params, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Page[ImageOut]:
    """The image gallery across the caller's conversations. Query params:
    ``page`` and ``size``; ``total`` on the page counts every image."""
    page = await list_client_images(db, caller.id, params)
    logger.info(
        "images_page_fetched",
        "Fetched paginated images",
        item_count=len(page.items),
        total=page.total,
        page=params.page,
        size=params.size,
    )
    return page


@router.get(
    "/download/{conversation_id}/{message_id}/{blob_id}",
    summary="Download a file (streamed, HTTP byte ranges supported)",
)
async def download_blob(
    conversation_id: str,
    message_id: str,
    blob_id: str,
    caller: Annotated[Caller, Depends(get_caller)],
    _rate_limited: Annotated[None, Depends(conversation_rate_limit)],
    db: Annotated[AsyncSession, Depends(get_db)],
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    """Stream a file as a download (images included): 200, or 206 for a range."""
    return await stream_blob_response(
        client_id=caller.id,
        conversation_id=conversation_id,
        message_id=message_id,
        blob_id=blob_id,
        range_header=range_header,
        db=db,
        disposition="attachment",
    )


@router.get(
    "/preview/{conversation_id}/{message_id}/{blob_id}",
    summary="Stream a non-image file inline for the in-app preview",
)
async def preview_blob(
    conversation_id: str,
    message_id: str,
    blob_id: str,
    caller: Annotated[Caller, Depends(get_caller)],
    _rate_limited: Annotated[None, Depends(conversation_rate_limit)],
    db: Annotated[AsyncSession, Depends(get_db)],
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    """Stream a file inline (PDF, text, Office documents...) under a sandbox CSP.
    Images are refused (400); HTML, SVG, JS and XML are served as downloads."""
    return await stream_blob_response(
        client_id=caller.id,
        conversation_id=conversation_id,
        message_id=message_id,
        blob_id=blob_id,
        range_header=range_header,
        db=db,
        disposition="inline",
    )
