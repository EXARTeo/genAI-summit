"""Data dictionary + GenerationSpec: loading, validation, merging, hashing.

The **data dictionary** (plugin ``data/data-dictionary.yaml``) is the business
logic: fields, roles, distributions, conditionals, rules, label rule, population
stats. The **GenerationSpec** (drafted by the LLM, approved by a human) points at
the dictionary, overrides fields (every override carries a ``provenance``), adds
rules and declares the test transforms. Unknown fields or unknown ops are refused
at load time (pipeline step G2), never at sampling time.

GenerationSpec (YAML)::

    version: 1
    name: SYS-001.cv-ranker.counterfactual-twins
    dictionary: data-dictionary.yaml       # relative to the spec file
    plugin: plugin.yaml                    # optional: protected/proxy hints, signature
    model_profile: model-profile.json      # optional: boundary-aware sampling
    n: 400                                 # base rows
    fields: {postcode_region: {conditional: {...}, provenance: llm_assumption}}
    rules: [{id: S1, severity: hard, expr: "...", provenance: memory}]
    strata: {by: [nationality], balance: true}            # base rows balanced per cell
    boundary: {share: 0.3, band: 0.15, pool: 5}           # needs model_profile
    coverage: {cells: [sex, nationality], min_per_cell: 30}
    transforms:
      - {kind: twins, attribute: nationality, modes: [attribute_only, causal, proxy_only],
         proxies: [postcode_region], max_base: 200}
      - {kind: edge_cases, fields: [years_experience, career_gap_months]}
      - {kind: perturbation, fields: [years_experience], delta: 1}
    custom: custom.py                      # optional escape hatch (flagged ai_generated)
    output: {columns: model_input | all}
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from synthkit.expr import ExpressionError, compile_expr, names
from synthkit.reference import ReferenceSampleError, apply_reference

FIELD_TYPES = frozenset({"category", "integer", "float", "string", "boolean", "id"})
ROLES = frozenset({"protected", "proxy", "feature", "label", "id", "surface"})
DISTS = frozenset(
    {"poisson", "lognormal", "normal", "uniform", "beta", "choice", "exponential", "empirical"}
)
GENERATION_MODES = ("zero_shot", "reference_sample")
TRANSFORMS = frozenset({"twins", "edge_cases", "perturbation"})
TWIN_MODES = ("attribute_only", "causal", "proxy_only")
SOURCE_KINDS = frozenset({"sequence", "list", "faker", "custom", "constant"})


class SpecError(ValueError):
    """The dictionary or spec is invalid; the message says where."""


def load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SpecError(f"cannot read {path}: {exc}") from exc


def canonical_hash(obj: Any) -> str:
    data = json.dumps(obj, sort_keys=True, default=str, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict) and key != "conditional":
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def field_parents(fdef: dict) -> list[str]:
    """Every field a field's sampling reads: depends_on, expressions, sources."""
    parents = list(fdef.get("depends_on") or [])
    cond = fdef.get("conditional")
    exprs: list[str] = []
    for holder in [cond, fdef.get("distribution")]:
        if isinstance(holder, dict):
            exprs += [v for k, v in holder.items() if k.endswith("_expr") and isinstance(v, str)]
    source = fdef.get("source") or {}
    parents += list(source.get("from_fields") or [])
    for key in ("locale_from", "gender_from"):
        if source.get(key):
            parents.append(source[key])
    for e in exprs:
        parents += sorted(names(e))
    seen: list[str] = []
    for p in parents:
        if p not in seen:
            seen.append(p)
    return seen


def validate_fields(fields: dict[str, dict]) -> None:
    if not fields:
        raise SpecError("no fields")
    for name, fdef in fields.items():
        where = f"field {name!r}"
        if not isinstance(fdef, dict):
            raise SpecError(f"{where}: must be a mapping")
        ftype = fdef.get("type")
        if ftype not in FIELD_TYPES:
            raise SpecError(f"{where}: unknown type {ftype!r}")
        role = fdef.get("role", "feature")
        if role not in ROLES:
            raise SpecError(f"{where}: unknown role {role!r}")
        for parent in field_parents(fdef):
            if parent not in fields:
                raise SpecError(f"{where}: depends on unknown field {parent!r}")
        dist = fdef.get("distribution")
        if isinstance(dist, dict) and "dist" in dist and dist["dist"] not in DISTS:
            raise SpecError(f"{where}: unknown dist {dist['dist']!r}")
        cond = fdef.get("conditional")
        if isinstance(cond, dict):
            items = [cond] if "dist" in cond else [v for v in cond.values() if isinstance(v, dict)]
            for item in items:
                if "dist" in item and item["dist"] not in DISTS:
                    raise SpecError(f"{where}: unknown dist {item['dist']!r}")
        source = fdef.get("source")
        if source and source.get("kind") not in SOURCE_KINDS:
            raise SpecError(f"{where}: unknown source kind {source.get('kind')!r}")
        rng = fdef.get("range")
        if rng is not None and (len(rng) != 2 or rng[0] > rng[1]):
            raise SpecError(f"{where}: range must be [min, max]")


def validate_rules(rules: list[dict], fields: dict) -> None:
    seen = set()
    for rule in rules:
        rid = rule.get("id")
        if not rid or rid in seen:
            raise SpecError(f"rule ids must be unique and present: {rid!r}")
        seen.add(rid)
        if rule.get("severity", "hard") not in ("hard", "soft"):
            raise SpecError(f"rule {rid}: severity must be hard|soft")
        try:
            unknown = names(rule["expr"]) - set(fields)
        except (ExpressionError, KeyError) as exc:
            raise SpecError(f"rule {rid}: {exc}") from exc
        if unknown:
            raise SpecError(f"rule {rid}: unknown fields {sorted(unknown)}")


def topo_order(fields: dict[str, dict]) -> list[str]:
    order: list[str] = []
    state: dict[str, int] = {}

    def visit(name: str) -> None:
        if state.get(name) == 2:
            return
        if state.get(name) == 1:
            raise SpecError(f"dependency cycle through {name!r}")
        state[name] = 1
        for parent in field_parents(fields[name]):
            visit(parent)
        state[name] = 2
        order.append(name)

    for name in fields:
        visit(name)
    return order


@dataclass
class Dictionary:
    """A loaded, validated data dictionary."""

    fields: dict[str, dict]
    rules: list[dict] = field(default_factory=list)
    label_rule: dict | None = None
    population: dict = field(default_factory=dict)
    source: str = ""

    @classmethod
    def from_mapping(cls, data: dict, source: str = "") -> Dictionary:
        if not isinstance(data, dict):
            raise SpecError("dictionary must be a mapping")
        fields = data.get("fields") or {}
        validate_fields(fields)
        rules = list(data.get("rules") or [])
        validate_rules(rules, fields)
        label_rule = data.get("label_rule")
        if label_rule:
            try:
                compile_expr(label_rule["expr"])
            except (ExpressionError, KeyError) as exc:
                raise SpecError(f"label_rule: {exc}") from exc
        topo_order(fields)
        return cls(fields, rules, label_rule, data.get("population") or {}, source)

    @classmethod
    def load(cls, path: Path) -> Dictionary:
        return cls.from_mapping(load_yaml(path), str(path))

    def by_role(self, *roles: str) -> list[str]:
        return [n for n, f in self.fields.items() if f.get("role", "feature") in roles]


@dataclass
class GenerationSpec:
    raw: dict
    base_dir: Path
    dictionary: Dictionary
    plugin: dict
    profile: dict | None
    custom_path: Path | None
    reference: dict | None = None  # reference_sample mode: provenance + fit report
    reference_frame: Any = None  # the reference mapped onto our fields (pandas)

    @property
    def mode(self) -> str:
        return str((self.raw.get("generation") or {}).get("mode", "zero_shot"))

    @property
    def n(self) -> int:
        return int(self.raw.get("n", 200))

    @property
    def name(self) -> str:
        return str(self.raw.get("name", "synthetic-dataset"))

    def hash(self) -> str:
        """Hash of everything that decides the rows: spec, merged dictionary, custom code."""
        custom = self.custom_path.read_text(encoding="utf-8") if self.custom_path else None
        profile_boundary = (self.profile or {}).get("decision_boundary")
        return canonical_hash(
            {
                "spec": self.raw,
                "fields": self.dictionary.fields,
                "rules": self.dictionary.rules,
                "label_rule": self.dictionary.label_rule,
                "custom": custom,
                "boundary": profile_boundary if self.raw.get("boundary") else None,
                "reference": (self.reference or {}).get("sha256"),
            }
        )


def _validate_spec_keys(raw: dict, fields: dict) -> None:
    for t in raw.get("transforms") or []:
        kind = t.get("kind")
        if kind not in TRANSFORMS:
            raise SpecError(f"unknown transform {kind!r}")
        if kind == "twins":
            attr = t.get("attribute")
            if attr not in fields:
                raise SpecError(f"twins: unknown attribute {attr!r}")
            for mode in t.get("modes") or TWIN_MODES:
                if mode not in TWIN_MODES:
                    raise SpecError(f"twins: unknown mode {mode!r}")
            for proxy in t.get("proxies") or []:
                if proxy not in fields:
                    raise SpecError(f"twins: unknown proxy {proxy!r}")
        for f in t.get("fields") or []:
            if f not in fields:
                raise SpecError(f"{kind}: unknown field {f!r}")
    for key in ("strata", "coverage"):
        block = raw.get(key) or {}
        for f in block.get("by") or block.get("cells") or []:
            if f not in fields and f != "_test":
                raise SpecError(f"{key}: unknown field {f!r}")


def load_spec(path: Path) -> GenerationSpec:
    path = Path(path)
    raw = load_yaml(path)
    if not isinstance(raw, dict):
        raise SpecError("spec must be a mapping")
    base = path.parent
    if "dictionary" not in raw:
        raise SpecError("spec needs `dictionary` (path to data-dictionary.yaml)")
    dict_data = load_yaml(base / raw["dictionary"])
    if not isinstance(dict_data, dict):
        raise SpecError("dictionary must be a mapping")
    fields = dict_data.get("fields") or {}
    for name, override in (raw.get("fields") or {}).items():
        if name not in fields:
            raise SpecError(f"spec overrides unknown field {name!r} (not in the dictionary)")
        merged = _deep_merge(fields[name], override)
        merged.setdefault("provenance", "llm_assumption")
        if "provenance" not in override:
            merged["provenance"] = "llm_assumption"
        fields[name] = merged
    dict_data["fields"] = fields
    extra_rules = []
    for rule in raw.get("rules") or []:
        rule = dict(rule)
        rule.setdefault("provenance", "llm_assumption")
        extra_rules.append(rule)
    dict_data["rules"] = list(dict_data.get("rules") or []) + extra_rules
    if raw.get("label_rule"):
        dict_data["label_rule"] = raw["label_rule"]
    mode = (raw.get("generation") or {}).get("mode", "zero_shot")
    if mode not in GENERATION_MODES:
        raise SpecError(f"generation.mode must be one of {GENERATION_MODES}")
    reference = reference_frame = None
    if mode == "reference_sample":
        validate_fields(dict_data["fields"])
        try:
            dict_data, reference, reference_frame = apply_reference(
                raw, base, dict_data, topo_order(dict_data["fields"])
            )
        except (ReferenceSampleError, OSError, ValueError, KeyError) as exc:
            raise SpecError(f"reference_sample: {exc}") from exc
    dictionary = Dictionary.from_mapping(dict_data, str(base / raw["dictionary"]))
    _validate_spec_keys(raw, dictionary.fields)
    plugin = load_yaml(base / raw["plugin"]) if raw.get("plugin") else {}
    profile = None
    if raw.get("model_profile"):
        profile_path = base / raw["model_profile"]
        if profile_path.exists():
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
        elif raw.get("boundary"):
            raise SpecError(f"boundary sampling needs the model profile: {profile_path}")
    custom = base / raw["custom"] if raw.get("custom") else None
    if custom is not None and not custom.exists():
        raise SpecError(f"custom sampler file not found: {custom}")
    return GenerationSpec(
        raw, base, dictionary, plugin or {}, profile, custom, reference, reference_frame
    )
