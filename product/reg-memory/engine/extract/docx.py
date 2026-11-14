"""DOCX -> text with the standard library (zip + WordprocessingML)."""

from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET  # noqa: S405 - local zip entries, not network XML

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_to_text(raw: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)  # noqa: S314 - see import note
    lines: list[str] = []
    for para in root.iter(f"{_W}p"):
        style = para.find(f"{_W}pPr/{_W}pStyle")
        parts = []
        for node in para.iter():
            if node.tag == f"{_W}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{_W}tab":
                parts.append("\t")
            elif node.tag in {f"{_W}br", f"{_W}cr"}:
                parts.append("\n")
        text = "".join(parts).strip()
        if not text:
            continue
        level = re.search(r"Heading(\d)", style.get(f"{_W}val", "")) if style is not None else None
        lines.append(f"{'#' * int(level.group(1))} {text}" if level else text)
    return "\n\n".join(lines) + "\n"
