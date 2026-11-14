"""``fetch_public_dataset``: an APPROVED candidate -> ``datasets/public/<slug>/``.

Files (synthkit reference mode reads the first two)::

    data.csv        capped rows, original column names, obvious PII columns dropped
    mapping.yaml    our dictionary field -> their column (+ transform, value map), label
    datasheet.md    source, licence, citation, columns, mapping, gaps, known biases
    source.json     the candidate as found (catalogue metadata) + who approved it

Stored through a :class:`Store`: :class:`BackendStore` (the backend's internal
route ``PUT /internal/audits/{id}/datasets/public/{slug}/{name}``) or
:class:`LocalStore` (a folder, for the CLI and tests).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Protocol

import httpx
import yaml

from harness.tools.public_datasets import sources
from harness.tools.public_datasets.scoring import licence_status, norm

DEFAULT_MAX_ROWS = 5000
DEFAULT_MAX_BYTES = 20_000_000

#: Column names that hold direct identifiers. Dropped when their values look like
#: identifiers (free text, high cardinality, or e-mail/phone patterns).
PII_NAMES = {
    "name",
    "first name",
    "last name",
    "surname",
    "full name",
    "given name",
    "email",
    "e mail",
    "mail",
    "phone",
    "telephone",
    "mobile",
    "phone number",
    "address",
    "street",
    "ssn",
    "social security",
    "passport",
    "iban",
    "ip",
    "ip address",
    "national id",
    "date of birth",
    "dob",
    "birth date",
}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.IGNORECASE)
_PHONE = re.compile(r"^\+?[\d\s().-]{7,}$")


class Store(Protocol):
    def write(self, name: str, content: str, content_type: str) -> dict[str, Any]: ...


class LocalStore:
    def __init__(self, root: Path, slug: str) -> None:
        self.dir = Path(root) / "datasets" / "public" / slug
        self.dir.mkdir(parents=True, exist_ok=True)

    def write(self, name: str, content: str, content_type: str) -> dict[str, Any]:
        path = self.dir / name
        path.write_text(content, encoding="utf-8", newline="")
        return {"path": str(path), "bytes": len(content.encode("utf-8"))}


class BackendStore:
    """Writes through the backend's internal API (shared secret, scoped to one audit)."""

    def __init__(
        self,
        base_url: str,
        audit_id: str,
        slug: str,
        secret: str,
        *,
        client: httpx.Client | None = None,
        run_id: str | None = None,
        trace_id: str | None = None,
        agent: str = "public-datasets",
    ) -> None:
        self.url = f"{base_url.rstrip('/')}/internal/audits/{audit_id}/datasets/public/{slug}"
        self.client = client or httpx.Client(timeout=60)
        self.headers = {"X-Internal-Secret": secret, "X-Agent-Name": agent}
        if run_id:
            self.headers["X-Run-Id"] = run_id
        if trace_id:
            self.headers["X-Trace-Id"] = trace_id

    def write(self, name: str, content: str, content_type: str) -> dict[str, Any]:
        response = self.client.put(
            f"{self.url}/{name}",
            json={"content": content, "contentType": content_type},
            headers=self.headers,
        )
        response.raise_for_status()
        body = response.json()
        return {"path": body["file"]["path"], "version": body["file"]["version"]}


def _looks_like_identifier(values: list[str]) -> bool:
    vals = [v for v in values if v]
    if not vals:
        return False
    if sum(bool(_EMAIL.match(v)) for v in vals) / len(vals) > 0.2:
        return True
    if (
        sum(bool(_PHONE.match(v)) and sum(c.isdigit() for c in v) >= 7 for v in vals) / len(vals)
        > 0.5
    ):
        return True
    return len(set(vals)) / len(vals) > 0.5 and any(not _is_number(v) for v in vals)


def _is_number(v: str) -> bool:
    try:
        float(v)
    except ValueError:
        return False
    return True


def find_pii_columns(header: list[str], rows: list[list[str]]) -> list[dict[str, str]]:
    """Columns to drop: identifier-like names with identifier-like values, or e-mails anywhere."""
    drop = []
    for i, col in enumerate(header):
        values = [r[i] for r in rows[:500] if i < len(r)]
        name = norm(col)
        named = name in PII_NAMES or any(name.endswith(f" {p}") for p in PII_NAMES)
        emails = values and sum(bool(_EMAIL.match(v)) for v in values) / len(values) > 0.2
        if emails or (named and _looks_like_identifier(values)):
            drop.append({"column": col, "reason": "direct identifier (PII): dropped, not stored"})
    return drop


def _column_profile(header: list[str], rows: list[list[str]]) -> list[dict[str, Any]]:
    out = []
    for i, col in enumerate(header):
        values = [r[i] if i < len(r) else "" for r in rows]
        present = [v for v in values if v != ""]
        numeric = present and all(_is_number(v) for v in present)
        entry: dict[str, Any] = {
            "column": col,
            "kind": "numeric" if numeric else "categorical",
            "missing_share": round(1 - len(present) / max(len(values), 1), 4),
            "distinct": len(set(present)),
        }
        if numeric:
            nums = sorted(float(v) for v in present)
            entry.update(min=nums[0], max=nums[-1], median=nums[len(nums) // 2])
        else:
            entry["top"] = dict(Counter(present).most_common(5))
        out.append(entry)
    return out


def _representation(
    mapping: dict[str, Any], header: list[str], rows: list[list[str]], protected: list[str]
) -> dict[str, dict[str, float]]:
    """Share of each mapped protected value in the reference (for the bias note)."""
    out: dict[str, dict[str, float]] = {}
    for f in protected:
        m = mapping.get(f)
        if not m or m["column"] not in header:
            continue
        i = header.index(m["column"])
        values = [r[i] for r in rows if i < len(r)]
        if m.get("values"):
            values = [m["values"].get(v, "unmapped") for v in values]
        elif m.get("transform") == "bin":
            continue  # numeric; the binned shares come out of synthkit
        counts = Counter(values)
        out[f] = {k: round(v / max(len(values), 1), 4) for k, v in counts.most_common(8)}
    return out


def build_mapping(scored: dict[str, Any], full: dict[str, Any], dropped: list[dict]) -> dict:
    dropped_cols = {d["column"] for d in dropped}
    fields = {
        f: {k: v for k, v in m.items() if k != "column_description"}
        for f, m in scored["mapping"].items()
        if m["column"] not in dropped_cols
    }
    return {
        "version": 1,
        "source": {
            "id": scored["id"],
            "name": scored["name"],
            "url": scored["url"],
            "licence": scored["licence"]["normalised"],
            "licence_status": scored["licence"]["status"],
            "citation": scored.get("citation") or full.get("citation") or "",
        },
        "plugin": scored["plugin"],
        "dataset": "data.csv",
        "fields": fields,
        "label": scored.get("label"),
        "unmapped": scored["gaps"],
        "dropped_columns": dropped,
        "notes": [
            "Review every value map: unmapped reference values are dropped at fit time.",
            "Units are not converted (e.g. DM vs EUR); add `scale:` per field if needed.",
        ],
    }


def datasheet(
    scored: dict[str, Any],
    full: dict[str, Any],
    mapping: dict[str, Any],
    profile: list[dict[str, Any]],
    representation: dict[str, dict[str, float]],
    rows: int,
    sha256: str,
    approved_by: str,
) -> str:
    lic = scored["licence"]
    lines = [
        f"# Datasheet: {scored['name']}",
        "",
        "| | |",
        "| --- | --- |",
        f"| Source | [{scored['id']}]({scored['url']}) |",
        f"| Licence | {lic['normalised']} ({lic['status']}) |",
        f"| Citation | {mapping['source']['citation'] or 'see source page'} |",
        f"| Collected / updated | {full.get('updated') or 'unknown'} |",
        f"| Rows stored | {rows} (capped) of {scored.get('n_rows') or '?'} |",
        f"| data.csv sha256 | `{sha256}` |",
        f"| Match score | {scored['score']} for plugin `{scored['plugin']}` |",
        f"| Approved by | {approved_by} |",
        "",
        "## Use",
        "",
        "Reference sample for synthkit `generation.mode: reference_sample`: marginals and "
        "conditionals are fitted from it along our dictionary's DAG; the dictionary's hard "
        "rules still apply. Never used as test rows directly.",
        "",
        "## Mapping to our dictionary",
        "",
        "| Our field | Their column | Transform | Value map |",
        "| --- | --- | --- | --- |",
    ]
    for f, m in mapping["fields"].items():
        vm = ", ".join(f"{k}->{v}" for k, v in (m.get("values") or {}).items()) or "-"
        lines.append(f"| {f} | {m['column']} | {m.get('transform', '-')} | {vm} |")
    if mapping.get("label"):
        lab = mapping["label"]
        lines.append(f"\nLabel: `{lab['column']}` -> `{lab['name']}` {lab.get('values') or ''}")
    lines += [
        "",
        f"Not in this dataset (sampled zero-shot from the dictionary): "
        f"{', '.join(mapping['unmapped']) or 'none'}.",
        "",
        "## Columns",
        "",
        "| Column | Kind | Missing | Distinct | Summary |",
        "| --- | --- | --- | --- | --- |",
    ]
    for c in profile:
        summary = (
            f"min {c['min']}, median {c['median']}, max {c['max']}"
            if c["kind"] == "numeric"
            else ", ".join(f"{k} ({v})" for k, v in c.get("top", {}).items())
        )
        lines.append(
            f"| {c['column']} | {c['kind']} | {c['missing_share']} | {c['distinct']} | {summary} |"
        )
    lines += ["", "## PII", ""]
    if mapping["dropped_columns"]:
        lines += [f"- `{d['column']}`: {d['reason']}" for d in mapping["dropped_columns"]]
    else:
        lines.append("No direct identifier columns found (names, e-mails, phones, addresses).")
    lines += ["", "## Known biases and limits", ""]
    for f, shares in representation.items():
        lines.append(f"- Representation of `{f}` in the reference: {shares}.")
    lines += [
        f"- Collected {full.get('updated') or 'at an unknown date'} for a different population "
        "and purpose than the audited system; marginals may not match its applicants.",
        "- Historical outcomes can encode past discrimination; the label is reference only.",
    ]
    if lic["status"] != "allowed":
        lines.append(f"- Licence needs a human check before reuse: {lic['raw'] or 'not stated'}.")
    if scored.get("llm_note"):
        lines.append(f"- Reviewer note (Gemini): {scored['llm_note']}")
    return "\n".join(lines) + "\n"


def fetch_public_dataset(
    scored: dict[str, Any],
    full: dict[str, Any],
    *,
    store: Store,
    approved_by: str,
    client: httpx.Client | None = None,
    max_rows: int = DEFAULT_MAX_ROWS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    protected: list[str] | None = None,
) -> dict[str, Any]:
    """Download one human-approved candidate and store the four files."""
    if not approved_by:
        raise ValueError("fetch needs the approving human (HITL pick of the candidates artifact)")
    if licence_status(full.get("licence", ""))[1] == "non_commercial":
        raise ValueError(f"{scored['id']}: non-commercial licence; pick another candidate")
    own = client is None
    client = client or sources.new_client(timeout=60)
    try:
        header, rows = sources.load_rows(client, full, max_rows, max_bytes)
    finally:
        if own:
            client.close()
    if not header or not rows:
        raise ValueError(f"{scored['id']}: no rows downloaded")
    dropped = find_pii_columns(header, rows)
    keep = [i for i, h in enumerate(header) if h not in {d["column"] for d in dropped}]
    header = [header[i] for i in keep]
    rows = [[r[i] if i < len(r) else "" for i in keep] for r in rows]

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    data_csv = buf.getvalue()
    sha = hashlib.sha256(data_csv.encode("utf-8")).hexdigest()
    mapping = build_mapping(scored, full, dropped)
    mapping["rows"] = len(rows)
    mapping["sha256"] = sha
    profile = _column_profile(header, rows)
    representation = _representation(mapping["fields"], header, rows, protected or [])
    sheet = datasheet(scored, full, mapping, profile, representation, len(rows), sha, approved_by)
    source = {
        **{k: v for k, v in full.items() if k != "columns"},
        "approved_by": approved_by,
    }
    written = {
        "data.csv": store.write("data.csv", data_csv, "text/csv"),
        "mapping.yaml": store.write(
            "mapping.yaml",
            yaml.safe_dump(mapping, sort_keys=False, allow_unicode=True),
            "application/yaml",
        ),
        "datasheet.md": store.write("datasheet.md", sheet, "text/markdown"),
        "source.json": store.write(
            "source.json", json.dumps(source, indent=2, default=str), "application/json"
        ),
    }
    return {
        "id": scored["id"],
        "slug": scored["slug"],
        "folder": f"datasets/public/{scored['slug']}/",
        "rows": len(rows),
        "columns": header,
        "dropped_columns": dropped,
        "mapped_fields": sorted(mapping["fields"]),
        "unmapped_fields": mapping["unmapped"],
        "sha256": sha,
        "files": written,
        "licence": scored["licence"],
    }


def fetch_from_result(
    result: dict[str, Any], candidate_id: str, *, store: Store, approved_by: str, **kwargs: Any
) -> dict[str, Any]:
    """Fetch the candidate a human picked from a ``search_public_datasets`` result."""
    scored = next((c for c in result["candidates"] if c["id"] == candidate_id), None)
    full = (result.get("candidates_full") or {}).get(candidate_id)
    if scored is None or full is None:
        raise ValueError(f"{candidate_id} is not in the candidates list")
    kwargs.setdefault("protected", result.get("protected"))
    return fetch_public_dataset(scored, full, store=store, approved_by=approved_by, **kwargs)
