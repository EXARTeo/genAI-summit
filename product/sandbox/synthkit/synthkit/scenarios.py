"""``synthkit scenarios-check``: sanity analysis of a scenarios.yaml.

scenarios.yaml (drafted by the agent from the plugin, memory and the profile)::

    target: SYS-001.cv-ranker
    scenarios:
      - id: SC-01
        requirement: REQ.AIA.10.2.f.bias-examination
        target: SYS-001.cv-ranker
        template: counterfactual_twins   # group_fairness | counterfactual_twins | perturbation
                                         # | edge_cases | accuracy_per_subgroup | ...
        data_needs: {fields: [nationality, postcode_region], attribute: nationality,
                     twin_modes: [attribute_only, causal, proxy_only], n: 400}
        expected_behaviour: "No score gap between nationality twins"
        protected: [nationality]
        proxies: [postcode_region]

Per scenario: is it complete (requirement id, target, data needs, expected
behaviour), do its fields exist, does it match the plugin? Overall: which
protected attributes, known proxies, monotone fields, declared edge cases and
``must`` items are covered, and which obvious cases are missing (ranked higher
when the model profile shows the field moves the output).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from synthkit.spec import Dictionary

FAIRNESS_TEMPLATES = {
    "group_fairness",
    "counterfactual_twins",
    "search_discrimination",
    "accuracy_per_subgroup",
}
REQUIRED = ("id", "requirement", "target", "template", "data_needs", "expected_behaviour")


def check_scenarios(
    doc: dict, dictionary: Dictionary, plugin: dict, profile: dict | None = None
) -> dict:
    items = doc.get("scenarios") or []
    plugin_id = plugin.get("id")
    hints = plugin.get("scenarios") or {}
    fields = dictionary.fields
    protected = set(hints.get("protected_attributes") or dictionary.by_role("protected"))
    proxies = set(hints.get("known_proxies") or dictionary.by_role("proxy"))
    monotone = {f for f, d in fields.items() if d.get("monotone")}
    moving = {
        f for f, s in ((profile or {}).get("sensitivity") or {}).items() if s.get("moves_output")
    }

    per: list[dict[str, Any]] = []
    covered_protected: set[str] = set()
    covered_proxies: set[str] = set()
    covered_monotone: set[str] = set()
    templates: set[str] = set()
    twin_modes: dict[str, set[str]] = {}
    seen_ids: set[str] = set()
    for sc in items:
        issues: list[str] = []
        sid = str(sc.get("id", "?"))
        if sid in seen_ids:
            issues.append("duplicate id")
        seen_ids.add(sid)
        for key in REQUIRED:
            if not sc.get(key):
                issues.append(f"missing {key}")
        if plugin_id and sc.get("target") and sc["target"] != plugin_id:
            issues.append(f"target {sc['target']!r} is not this plugin ({plugin_id})")
        needs = sc.get("data_needs") or {}
        named = (
            set(needs.get("fields") or [])
            | set(sc.get("protected") or [])
            | set(sc.get("proxies") or [])
        )
        if needs.get("attribute"):
            named.add(needs["attribute"])
        unknown = sorted(f for f in named if f not in fields)
        if unknown:
            issues.append(f"unknown fields {unknown}")
        template = sc.get("template", "")
        templates.add(template)
        sc_protected = set(sc.get("protected") or []) | (
            {needs["attribute"]} if needs.get("attribute") else set()
        )
        if template in FAIRNESS_TEMPLATES:
            covered_protected |= sc_protected & protected
            if not sc_protected:
                issues.append("fairness scenario names no protected attribute")
        covered_proxies |= (set(sc.get("proxies") or []) | set(needs.get("fields") or [])) & proxies
        if template in ("perturbation", "metamorphic"):
            covered_monotone |= set(needs.get("fields") or []) & monotone
        if template == "counterfactual_twins":
            for attr in sc_protected:
                twin_modes.setdefault(attr, set()).update(needs.get("twin_modes") or [])
        per.append(
            {
                "id": sid,
                "requirement": sc.get("requirement"),
                "template": template,
                "target": sc.get("target"),
                "fields": sorted(named),
                "expected_behaviour": sc.get("expected_behaviour"),
                "status": "ok" if not issues else "issues",
                "issues": issues,
            }
        )

    missing: list[dict[str, str]] = []

    def add(priority: str, what: str, why: str) -> None:
        missing.append({"priority": priority, "what": what, "why": why})

    for attr in sorted(protected - covered_protected):
        add("high", f"fairness test for {attr}", "protected attribute with no fairness scenario")
    for proxy in sorted(proxies - covered_proxies):
        prio = "high" if proxy in moving else "medium"
        why = "known proxy not tested" + (
            " and the profile shows it moves the output" if proxy in moving else ""
        )
        add(prio, f"proxy test for {proxy} (proxy-only twins)", why)
    for attr, modes in sorted(twin_modes.items()):
        attr_proxies = [p for p in proxies if attr in (fields.get(p, {}).get("proxy_for") or [])]
        if attr_proxies and not {"causal", "proxy_only"} & modes:
            add(
                "high",
                f"causal / proxy-only twins for {attr}",
                f"attribute-only twins cannot see discrimination through {attr_proxies}",
            )
    for f in sorted(monotone - covered_monotone):
        add("medium", f"metamorphic test: {f} {fields[f]['monotone']}", "declared monotone")
    edge_declared = hints.get("edge_cases") or []
    if edge_declared and "edge_cases" not in templates:
        add("medium", "edge-case scenario", f"plugin declares edge cases: {edge_declared}")
    if dictionary.label_rule and "accuracy_per_subgroup" not in templates:
        add(
            "low", "accuracy per subgroup", "a label_rule exists, so accuracy per group is testable"
        )
    for must in (plugin.get("expected_behaviour") or {}).get("must") or []:
        text = " ".join(str(s.get("expected_behaviour", "")) for s in items).lower()
        if not any(word in text for word in str(must).lower().split() if len(word) > 4):
            add("low", f"check for must: {must!r}", "expected_behaviour.must not referenced")
    for f in sorted((moving & protected) - covered_protected):
        add("high", f"{f} moves the output directly", "profile: protected attribute is used")

    return {
        "target": doc.get("target") or plugin_id,
        "n_scenarios": len(items),
        "scenarios": per,
        "coverage": {
            "protected": {a: a in covered_protected for a in sorted(protected)},
            "proxies": {p: p in covered_proxies for p in sorted(proxies)},
            "monotone": {m: m in covered_monotone for m in sorted(monotone)},
            "templates": sorted(t for t in templates if t),
        },
        "missing": sorted(missing, key=lambda m: {"high": 0, "medium": 1, "low": 2}[m["priority"]]),
        "status": "ok" if not missing and all(p["status"] == "ok" for p in per) else "gaps",
        "profile_used": profile is not None,
    }


def to_markdown(r: dict) -> str:
    lines = [
        f"# Scenario check: {r['target']}",
        "",
        f"{r['n_scenarios']} scenarios, status **{r['status']}**.",
        "",
        "| Scenario | Requirement | Template | Issues |",
        "| --- | --- | --- | --- |",
    ]
    for s in r["scenarios"]:
        lines.append(
            f"| {s['id']} | {s['requirement'] or '-'} | {s['template'] or '-'} | "
            f"{'; '.join(s['issues']) or 'ok'} |"
        )
    lines += ["", "## Missing", ""]
    lines += [f"- **{m['priority']}** {m['what']}: {m['why']}" for m in r["missing"]] or ["- none"]
    return "\n".join(lines) + "\n"


def write_report(r: dict, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "scenario-analysis.json").write_text(json.dumps(r, indent=2), encoding="utf-8")
    (out_dir / "scenario-analysis.md").write_text(to_markdown(r), encoding="utf-8")
