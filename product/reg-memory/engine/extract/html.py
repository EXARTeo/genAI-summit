"""XHTML/HTML -> markdown-ish text."""

from __future__ import annotations

import re
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from markdownify import markdownify

_DROP = ["script", "style", "noscript", "nav", "header", "footer", "form", "svg", "button"]
# Cellar XHTML marks structure with classes, not heading tags.
_HEADING_CLASSES = {
    "ti-art": "###",
    "oj-ti-art": "###",
    "ti-section-1": "##",
    "oj-ti-section-1": "##",
    "doc-ti": "#",
    "oj-doc-ti": "#",
    # Consolidated texts (CELEX 0....-YYYYMMDD) use their own classes.
    "title-division-1": "##",
    "title-annex-1": "##",
    "title-article-norm": "###",
}


def html_to_markdown(raw: bytes) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(_DROP):
        tag.decompose()
    for cls, level in _HEADING_CLASSES.items():
        for el in soup.find_all(class_=cls):
            el.name = f"h{len(level)}"
    root = soup.find("main") or soup.body or soup
    text = markdownify(
        str(root),
        heading_style="ATX",
        strip=["img", "a"],
        escape_misc=False,
        escape_asterisks=False,
        escape_underscores=False,
    )
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"
