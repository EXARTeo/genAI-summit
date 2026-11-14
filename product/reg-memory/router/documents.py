from fastapi import APIRouter, Depends, Query

from core.security.rate_limit import read_rate_limit
from schema.documents import DocumentDetail, DocumentList, DocumentText
from utils.documents import get_document, get_text, list_documents

router = APIRouter(dependencies=[Depends(read_rate_limit)])


@router.get("", response_model=DocumentList)
async def documents(source_id: str | None = None) -> DocumentList:
    return list_documents(source_id)


@router.get("/{doc_id}", response_model=DocumentDetail)
async def document(doc_id: str) -> DocumentDetail:
    return get_document(doc_id)


@router.get("/{doc_id}/text", response_model=DocumentText)
async def document_text(doc_id: str, version: int | None = Query(None, ge=1)) -> DocumentText:
    return get_text(doc_id, version)
