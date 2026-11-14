"""Pick the extractor for a stored raw file, by extension (decided from magic bytes
first: some servers send ``Content-Type: /``)."""

from __future__ import annotations

from engine.extract.docx import docx_to_text
from engine.extract.html import html_to_markdown
from engine.extract.pdf import pdf_to_text

EXT_BY_TYPE = {
    "application/xhtml+xml": "xhtml",
    "text/html": "html",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/markdown": "md",
    "text/plain": "txt",
}
BINARY_EXTS = frozenset({"pdf", "docx", "zip", "bin"})


def guess_ext(content_type: str, content: bytes, filename: str | None = None) -> str:
    if content.startswith(b"%PDF"):
        return "pdf"
    if content.startswith(b"PK\x03\x04"):
        return "docx" if b"word/document.xml" in content else "zip"
    if ext := EXT_BY_TYPE.get(content_type):
        return ext
    head = content[:1024].lstrip().lower()
    if head.startswith((b"<!doctype html", b"<html", b"<?xml")) or b"<html" in head:
        return "html"
    if filename and "." in filename:
        return filename.rsplit(".", 1)[-1].lower()[:8]
    return "bin"


def extract_text(raw: bytes, ext: str) -> str:
    if ext in {"xhtml", "html"}:
        return html_to_markdown(raw)
    if ext == "pdf":
        return pdf_to_text(raw)
    if ext == "docx":
        return docx_to_text(raw)
    if ext in {"md", "txt"}:
        return raw.decode("utf-8", errors="replace")
    raise ValueError(f"no extractor for .{ext}")
