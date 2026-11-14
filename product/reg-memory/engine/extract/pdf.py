"""PDF -> text (pypdf), one ``<!-- page N -->`` marker per page."""

from __future__ import annotations

import io
import logging

from pypdf import PdfReader

logging.getLogger("pypdf").setLevel(logging.ERROR)


def pdf_to_text(raw: bytes) -> str:
    reader = PdfReader(io.BytesIO(raw))
    parts = []
    for n, page in enumerate(reader.pages, start=1):
        parts.append(f"<!-- page {n} -->\n{(page.extract_text() or '').strip()}\n")
    return "\n".join(parts)
