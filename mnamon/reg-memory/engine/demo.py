"""The demo mirror: an editable copy of an Art. 6 guideline page, served by
reg-memory itself, so "edit -> check now -> RegChange" works live and offline.

    <data>/demo/art6-guidelines.html    seeded from the template below on first use
"""

from __future__ import annotations

from pathlib import Path

from engine.store import _atomic_write

MIRROR_NAME = "art6-guidelines.html"

DEFAULT_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Guidelines on the classification of high-risk AI systems (demo mirror)</title>
</head>
<body>
<main>
<h1>Guidelines on the classification of high-risk AI systems (Article 6)</h1>
<p><em>Demo mirror of a Commission guideline page. Not an official EU source.</em></p>

<h2>1. Purpose</h2>
<p>These guidelines explain the practical implementation of Article 6 of Regulation (EU)
2024/1689, including the derogation in Article 6(3) for AI systems listed in Annex III that
do not pose a significant risk of harm.</p>

<h2>2. Employment: recruitment and selection</h2>
<p>AI systems intended to be used for the recruitment or selection of natural persons, in
particular to analyse and filter job applications and to evaluate candidates, fall under
point 4(a) of Annex III. A CV screening system that ranks applicants for a shortlist is
high-risk under Article 6(2).</p>
<p>Example 12: a system that only converts CVs into a structured format, without ranking or
filtering, performs a narrow procedural task within the meaning of Article 6(3), point (a),
and is not considered high-risk, provided the provider documents its assessment under
Article 6(4).</p>

<h2>3. Creditworthiness</h2>
<p>AI systems used to evaluate the creditworthiness of natural persons or establish their
credit score fall under point 5(b) of Annex III, except systems used to detect financial
fraud.</p>

<h2>4. Bias examination</h2>
<p>Providers should examine training, validation and testing data for possible biases as
required by Article 10(2), point (f), including bias introduced through proxies such as
postcode or career gaps.</p>
</main>
</body>
</html>
"""


def mirror_path(data_dir: Path) -> Path:
    return Path(data_dir) / "demo" / MIRROR_NAME


def read_mirror(data_dir: Path) -> str:
    path = mirror_path(data_dir)
    if not path.exists():
        _atomic_write(path, DEFAULT_HTML.encode("utf-8"))
    return path.read_text(encoding="utf-8")


def write_mirror(data_dir: Path, html: str) -> str:
    _atomic_write(mirror_path(data_dir), html.encode("utf-8"))
    return html


def edit_mirror(
    data_dir: Path,
    *,
    html: str | None = None,
    find: str | None = None,
    replace: str | None = None,
    append_html: str | None = None,
    reset: bool = False,
) -> str:
    """Replace the page, find/replace in it, append a block before ``</main>``, or reset."""
    if reset:
        return write_mirror(data_dir, DEFAULT_HTML)
    if html is not None:
        return write_mirror(data_dir, html)
    page = read_mirror(data_dir)
    if find is not None:
        if find not in page:
            raise ValueError("text to replace not found in the mirror")
        page = page.replace(find, replace or "", 1)
    if append_html:
        marker = "</main>"
        idx = page.rfind(marker)
        page = page[:idx] + append_html + "\n" + page[idx:] if idx >= 0 else page + append_html
    return write_mirror(data_dir, page)
