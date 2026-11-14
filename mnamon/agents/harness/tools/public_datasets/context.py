"""System folder → :class:`SystemContext` per plugin, and search queries.

Reads the same files the agent reads (agent-context.md §2-§3): ``system-card.yaml``,
``plugins/<p>/plugin.yaml``, ``plugins/<p>/data/data-dictionary.yaml`` and
``training-data.md``. Works on a dict of ``{path: text}`` so the caller decides
where the files come from (a local folder, or the backend's internal API).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from harness.tools.public_datasets.models import Field, SystemContext

#: Domain hints: how a system card's purpose maps to catalogue searches. Picked by
#: the EU AI Act Annex III point first, then by keywords in the card.
DOMAINS: dict[str, dict[str, Any]] = {
    "credit": {
        "annex": ["5(b)"],
        "keywords": ["credit", "loan", "lending", "creditworth", "repay"],
        "queries": ["german credit", "credit risk", "credit scoring", "loan default"],
        "openml_names": ["credit-g", "credit-approval", "default-of-credit-card-clients"],
        "openml_tags": ["credit_scoring"],
        "uci_terms": ["credit"],
    },
    "employment": {
        "annex": ["4(a)", "4(b)"],
        "keywords": ["cv", "recruit", "hiring", "shortlist", "applicants for", "candidate"],
        "queries": ["recruitment", "hiring decisions", "job applicants", "resume screening"],
        "openml_names": [],
        "openml_tags": [],
        "uci_terms": ["employee", "recruitment", "hiring"],
    },
    "benefits": {
        "annex": ["5(a)"],
        "keywords": ["benefit", "welfare", "minimum-income", "eligibility", "household"],
        "queries": ["census income", "household income", "social benefits eligibility"],
        "openml_names": ["adult"],
        "openml_tags": [],
        "uci_terms": ["adult", "census income"],
    },
}

GENERIC_QUERIES = ["fairness"]


def _yaml(text: str | None) -> dict:
    if not text:
        return {}
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {}


def read_system_dir(root: Path) -> dict[str, str]:
    """Every yaml/md file of a local system folder, keyed by its relative path."""
    root = Path(root)
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_file() and path.suffix in (".yaml", ".yml", ".md") and not rel.startswith("_"):
            out[rel] = path.read_text(encoding="utf-8")
    return out


def _fields(dictionary: dict) -> dict[str, Field]:
    out: dict[str, Field] = {}
    for name, fdef in (dictionary.get("fields") or {}).items():
        if not isinstance(fdef, dict):
            continue
        values = fdef.get("values") or []
        dist = fdef.get("distribution")
        if not values and isinstance(dist, dict):
            inner = dist.get("values", dist if "dist" not in dist else {})
            values = list(inner) if isinstance(inner, dict) else []
        out[name] = Field(
            name=name,
            type=str(fdef.get("type", "unknown")),
            role=str(fdef.get("role", "feature")),
            values=[str(v) for v in values],
            synonyms=[str(s) for s in fdef.get("synonyms") or []],
            description=str(fdef.get("meaning") or fdef.get("description") or ""),
            depends_on=list(fdef.get("depends_on") or []),
        )
    return out


def _labels(dictionary: dict, plugin: dict, fields: dict[str, Field]) -> list[str]:
    names: list[str] = []
    rule = dictionary.get("label_rule") or {}
    if rule.get("name"):
        names.append(str(rule["name"]))
    names += [n for n, f in fields.items() if f.role == "label"]
    # A population rate over something that is not a field (``repaid.rate``) is the
    # outcome; one over a field's value (``unemployed.rate``) is not.
    field_values = {v for f in fields.values() for v in f.values}
    for key in (dictionary.get("population") or {}).get("stats") or {}:
        field_name, _, stat = str(key).partition(".")
        if stat == "rate" and field_name not in fields and field_name not in field_values:
            names.append(field_name)
    output = ((plugin.get("io") or {}).get("output")) or {}
    if isinstance(output, dict) and output.get("label_field"):
        names.append(str(output["label_field"]))
    elif isinstance(output, dict) and isinstance(output.get("columns"), dict):
        names += [str(c) for c in list(output["columns"])[:1]]
    seen: list[str] = []
    for n in names:
        if n not in seen:
            seen.append(n)
    return seen


def load_contexts(files: dict[str, str], system_id: str = "") -> list[SystemContext]:
    """One context per plugin that has a data dictionary."""
    card = _yaml(files.get("system-card.yaml"))
    system_id = system_id or str(card.get("id", ""))
    contexts: list[SystemContext] = []
    for path in sorted(files):
        parts = path.split("/")
        if (
            len(parts) != 4
            or parts[0] != "plugins"
            or parts[2:] != ["data", "data-dictionary.yaml"]
        ):
            continue
        plugin_name = parts[1]
        dictionary = _yaml(files[path])
        plugin = _yaml(files.get(f"plugins/{plugin_name}/plugin.yaml"))
        fields = _fields(dictionary)
        output = ((plugin.get("io") or {}).get("output")) or {}
        contexts.append(
            SystemContext(
                system_id=system_id,
                plugin=plugin_name,
                name=str(card.get("name", "")),
                purpose=" ".join(
                    str(x)
                    for x in [
                        card.get("intended_purpose", ""),
                        (plugin.get("expected_behaviour") or {}).get("task", ""),
                    ]
                    if x
                ),
                annex_basis=str(card.get("annex_basis", "")),
                task=str(output.get("type", "")) if isinstance(output, dict) else "",
                label_names=_labels(dictionary, plugin, fields),
                fields=fields,
                protected=[n for n, f in fields.items() if f.role == "protected"],
                proxies=[n for n, f in fields.items() if f.role == "proxy"],
                training_data=files.get(f"plugins/{plugin_name}/data/training-data.md", ""),
            )
        )
    return contexts


def domains_for(ctx: SystemContext) -> list[str]:
    hits = [d for d, spec in DOMAINS.items() if any(a in ctx.annex_basis for a in spec["annex"])]
    text = f"{ctx.name} {ctx.purpose}".lower()
    hits += [
        d
        for d, spec in DOMAINS.items()
        if d not in hits and any(k in text for k in spec["keywords"])
    ]
    return hits


def build_queries(ctx: SystemContext) -> dict[str, list[str]]:
    """Free-text queries (HF, UCI, Firecrawl) plus OpenML names/tags, deduplicated."""
    domains = domains_for(ctx)
    free: list[str] = []
    names: list[str] = []
    tags: list[str] = []
    uci: list[str] = []
    for d in domains:
        spec = DOMAINS[d]
        free += spec["queries"]
        names += spec["openml_names"]
        tags += spec["openml_tags"]
        uci += spec["uci_terms"]
    for label in ctx.label_names[:2]:
        if domains:
            free.append(f"{DOMAINS[domains[0]]['queries'][0]} {label}".strip())
    # The approved scenarios' protected attributes: datasets that carry them.
    for attr in ctx.scenario_protected[:2]:
        if domains:
            free.append(f"{DOMAINS[domains[0]]['queries'][0]} {attr.replace('_', ' ')}")
    if not free:  # no domain hint: fall back to the card's own words
        words = [w for w in ctx.name.lower().split() if len(w) > 3]
        free.append(" ".join(words[:3]) or ctx.plugin.replace("-", " "))
        uci.append(words[0] if words else ctx.plugin)

    def dedupe(xs: list[str]) -> list[str]:
        out: list[str] = []
        for x in xs:
            if x and x not in out:
                out.append(x)
        return out

    return {
        "domains": domains,
        "free_text": dedupe(free),
        "openml_names": dedupe(names),
        "openml_tags": dedupe(tags),
        "uci": dedupe(uci),
    }
