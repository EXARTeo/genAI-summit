"""kb releases: immutable snapshots of provisions + interpretations + requirements +
test templates, with id ``YYYY.MM.DD-N`` (the ``kb_version`` every finding pins).

    <data>/kb/
      releases/<kb_version>/
        manifest.json                     status, inputs (doc versions), hashes, counts, warnings
        index.json                        id -> {file, content_hash} (provisions, interpretations)
        provisions/<INSTR>/<group>.yaml   art_10.yaml, annex_III.yaml, recitals.yaml ...
        interpretations/<source_id>.yaml
        requirements.yaml, test_templates.yaml
      active.json                         {"kb_version", "activated_at", "activated_by"}

A new release is a ``candidate``; it becomes ``active`` only through an explicit
activation (the HITL accept, G6), except the very first one (the baseline) when
``REG_MEMORY_AUTO_ACTIVATE_FIRST`` is on. Old releases are kept; a build whose
content equals the latest release creates nothing.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from engine.catalog.loader import Catalog
from engine.kb.corpus import CORPUS_DIR, check_corpus, load_corpus
from engine.kb.interpretations import INTERPRETATION_KINDS, build_interpretations
from engine.kb.parser import PARSER_VERSION, link_amendments, parse_act, parse_recitals
from engine.store import Store, _atomic_write, now_iso

KB_VERSION_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}-\d+$")

#: (instrument, document id, what to parse). The consolidated text is the working text.
PROVISION_SOURCES: list[tuple[str, str, str]] = [
    ("AIA", "ai-act-consolidated", "act"),
    ("AIA", "ai-act", "recitals"),
    ("OMNIBUS", "digital-omnibus-ai", "act"),
    ("OMNIBUS", "digital-omnibus-ai", "recitals"),
]

try:  # libyaml when available: a release is a few MB of YAML
    _Dumper: Any = yaml.CSafeDumper
    _Loader: Any = yaml.CSafeLoader
except AttributeError:  # pragma: no cover
    _Dumper, _Loader = yaml.SafeDumper, yaml.SafeLoader


def _dump(data: Any) -> bytes:
    return yaml.dump(
        data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=10_000
    ).encode("utf-8")


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _group(prov: dict[str, Any]) -> str:
    """The YAML file a provision lives in: art_10, annex_III, recitals."""
    if prov["kind"] == "recital":
        return "recitals"
    head = prov["id"].split(".")[1]
    if head.startswith("ANNEX_"):
        return f"annex_{head[6:]}"
    return f"art_{head}"


class KnowledgeBase:
    """Releases, the active pointer and cached reads, on top of the store's data dir."""

    _cache: OrderedDict[tuple[str, str], Any] = OrderedDict()

    def __init__(self, store: Store, corpus_dir: Path = CORPUS_DIR) -> None:
        self.store = store
        self.root = store.root / "kb"
        self.corpus_dir = corpus_dir

    # ---- paths / ids ---------------------------------------------------------------------

    def release_dir(self, kb_version: str) -> Path:
        if not KB_VERSION_RE.match(kb_version):
            raise ValueError(f"invalid kb_version: {kb_version!r}")
        return self.root / "releases" / kb_version

    def _next_version(self) -> str:
        today = datetime.now(UTC).strftime("%Y.%m.%d")
        taken = [v for v in self.versions() if v.startswith(today + "-")]
        n = max((int(v.rsplit("-", 1)[1]) for v in taken), default=0) + 1
        return f"{today}-{n}"

    def versions(self) -> list[str]:
        folder = self.root / "releases"
        if not folder.exists():
            return []
        found = [p.name for p in folder.iterdir() if (p / "manifest.json").exists()]
        return sorted(found, key=lambda v: (v.rsplit("-", 1)[0], int(v.rsplit("-", 1)[1])))

    # ---- snapshot ---------------------------------------------------------------------------

    def snapshot(self, catalog: Catalog) -> dict[str, Any]:
        """Parse the latest texts into one in-memory snapshot (no files written)."""
        inputs: dict[str, dict[str, Any]] = {}
        provisions: list[dict[str, Any]] = []
        acts: dict[str, list[dict[str, Any]]] = {}
        for instrument, doc_id, what in PROVISION_SOURCES:
            found = self.store.read_text(doc_id)
            if not found:
                continue
            text, entry = found
            inputs[doc_id] = {"version": entry["version"], "sha256": entry["sha256"]}
            if what == "act":
                nodes = parse_act(text, instrument, source_doc=doc_id)
                acts[instrument] = nodes
            else:
                nodes = parse_recitals(text, instrument, source_doc=doc_id)
            provisions.extend(nodes)
        if "AIA" in acts and "OMNIBUS" in acts:
            labels = {a for p in acts["AIA"] for a in p["amended_by"] if "2026/1744" in a}
            for label in labels:
                link_amendments(acts["AIA"], acts["OMNIBUS"], label)
        known = {p["id"] for p in provisions}

        interpretations: list[dict[str, Any]] = []
        for manifest in self.store.list_manifests():
            source = catalog.get(manifest["source_id"])
            if not source or source.kind not in INTERPRETATION_KINDS or source.binding is True:
                continue
            found = self.store.read_text(manifest["doc_id"])
            if not found:
                continue
            text, entry = found
            inputs[manifest["doc_id"]] = {"version": entry["version"], "sha256": entry["sha256"]}
            doc = {**manifest, "version": entry["version"]}
            interpretations.extend(build_interpretations(doc, source, text, known))

        reqs, tts = load_corpus(self.corpus_dir)
        by_id = {p["id"]: p for p in provisions}
        for r in reqs:  # dates and the text hash of the source provision
            src = by_id.get(r["source"]) or {}
            r["valid_from"] = src.get("valid_from")
            if src.get("valid_from_by_basis"):
                r["valid_from_by_basis"] = src["valid_from_by_basis"]
            r["source_hash"] = src.get("content_hash")
        return {
            "provisions": provisions,
            "interpretations": interpretations,
            "requirements": reqs,
            "test_templates": tts,
            "inputs": inputs,
            "warnings": check_corpus(reqs, tts, known),
        }

    # ---- build -----------------------------------------------------------------------------

    def build_release(self, catalog: Catalog, *, trigger: str | None = None) -> tuple[dict, bool]:
        """Snapshot -> a new candidate release, unless identical to the latest one.

        Returns ``(manifest, created)``.
        """
        snap = self.snapshot(catalog)
        if not snap["provisions"]:
            raise RuntimeError("no provisions: the AI Act text has not been downloaded yet")
        files: dict[str, bytes] = {}
        index: dict[str, dict[str, Any]] = {"provisions": {}, "interpretations": {}}

        groups: dict[str, list[dict]] = {}
        for p in snap["provisions"]:
            groups.setdefault(f"provisions/{p['instrument']}/{_group(p)}.yaml", []).append(p)
        for path, items in groups.items():
            for p in items:
                index["provisions"][p["id"]] = {"file": path, "content_hash": p["content_hash"]}
        per_source: dict[str, list[dict]] = {}
        for it in snap["interpretations"]:
            per_source.setdefault(f"interpretations/{it['source_id']}.yaml", []).append(it)
        for path, items in per_source.items():
            for it in items:
                index["interpretations"][it["id"]] = {
                    "file": path,
                    "content_hash": it["content_hash"],
                }
        hashes = {
            "provisions": _sha(json.dumps(index["provisions"], sort_keys=True).encode()),
            "interpretations": _sha(json.dumps(index["interpretations"], sort_keys=True).encode()),
            "requirements": _sha(_dump(snap["requirements"])),
            "test_templates": _sha(_dump(snap["test_templates"])),
        }
        # The parser version is part of the release identity: a re-parse is a new release.
        content = _sha(json.dumps({**hashes, "parser": PARSER_VERSION}, sort_keys=True).encode())
        latest = self.latest_manifest()
        if latest and latest.get("content_hash") == content:
            return latest, False

        kb_version = self._next_version()
        for p in snap["provisions"]:
            p["kb_version"] = kb_version
        for it in snap["interpretations"]:
            it["kb_version"] = kb_version
        for path, items in {**groups, **per_source}.items():
            files[path] = _dump(items)
        files["requirements.yaml"] = _dump(snap["requirements"])
        files["test_templates.yaml"] = _dump(snap["test_templates"])
        files["index.json"] = json.dumps(index, ensure_ascii=False).encode("utf-8")
        manifest = {
            "kb_version": kb_version,
            "status": "candidate",
            "created_at": now_iso(),
            "trigger": trigger,
            "parent": latest["kb_version"] if latest else None,
            "content_hash": content,
            "parser_version": PARSER_VERSION,
            "hashes": hashes,
            "inputs": snap["inputs"],
            "counts": {
                "provisions": len(snap["provisions"]),
                "interpretations": len(snap["interpretations"]),
                "requirements": len(snap["requirements"]),
                "test_templates": len(snap["test_templates"]),
            },
            "warnings": snap["warnings"],
        }
        folder = self.release_dir(kb_version)
        for rel, data in files.items():
            _atomic_write(folder / rel, data)
        # The manifest last: a release without one is invisible (crash-safe).
        self._save_manifest(manifest)
        return manifest, True

    # ---- manifests and activation ---------------------------------------------------------

    def _save_manifest(self, manifest: dict[str, Any]) -> None:
        path = self.release_dir(manifest["kb_version"]) / "manifest.json"
        _atomic_write(path, json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"))

    def load_manifest(self, kb_version: str) -> dict[str, Any] | None:
        try:
            path = self.release_dir(kb_version) / "manifest.json"
        except ValueError:
            return None
        if not path.exists():
            return None
        manifest = json.loads(path.read_text(encoding="utf-8"))
        active = self.active_version()
        if manifest["kb_version"] == active:
            manifest["status"] = "active"
        elif manifest["status"] == "active":
            manifest["status"] = "superseded"
        return manifest

    def latest_manifest(self) -> dict[str, Any] | None:
        versions = self.versions()
        return self.load_manifest(versions[-1]) if versions else None

    def list_releases(self) -> list[dict[str, Any]]:
        return [m for v in reversed(self.versions()) if (m := self.load_manifest(v))]

    def active_version(self) -> str | None:
        path = self.root / "active.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8")).get("kb_version")

    def activate(self, kb_version: str, *, by: str = "api") -> dict[str, Any]:
        manifest = self.load_manifest(kb_version)
        if manifest is None:
            raise KeyError(kb_version)
        previous = self.active_version()
        manifest.update(status="active", activated_at=now_iso(), activated_by=by)
        self._save_manifest(manifest)
        pointer = {
            "kb_version": kb_version,
            "activated_at": manifest["activated_at"],
            "activated_by": by,
            "previous": previous,
        }
        _atomic_write(self.root / "active.json", json.dumps(pointer, indent=2).encode("utf-8"))
        return self.load_manifest(kb_version) or manifest

    def resolve(self, kb_version: str | None) -> str | None:
        """``kb_version`` or the active one (or the latest when none is active)."""
        if kb_version:
            return kb_version if self.load_manifest(kb_version) else None
        versions = self.versions()
        return self.active_version() or (versions[-1] if versions else None)

    # ---- cached reads ---------------------------------------------------------------------

    def _cached(self, key: tuple[str, str], loader: Any) -> Any:
        cache = KnowledgeBase._cache
        full = (str(self.root), *key)
        if full in cache:
            cache.move_to_end(full)
            return cache[full]
        value = loader()
        cache[full] = value
        while len(cache) > 24:
            cache.popitem(last=False)
        return value

    def _read_yaml(self, kb_version: str, rel: str) -> Any:
        path = self.release_dir(kb_version) / rel
        if not path.exists():
            return []
        return yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)  # noqa: S506 - safe loader or []

    def index(self, kb_version: str) -> dict[str, Any]:
        def load() -> dict[str, Any]:
            path = self.release_dir(kb_version) / "index.json"
            return json.loads(path.read_text(encoding="utf-8"))

        return self._cached((kb_version, "index"), load)

    def _all(self, kb_version: str, kind: str) -> list[dict[str, Any]]:
        def load() -> list[dict[str, Any]]:
            files = sorted({e["file"] for e in self.index(kb_version)[kind].values()})
            return [item for f in files for item in self._read_yaml(kb_version, f)]

        return self._cached((kb_version, kind), load)

    def provisions(self, kb_version: str) -> list[dict[str, Any]]:
        return self._all(kb_version, "provisions")

    def interpretations(self, kb_version: str) -> list[dict[str, Any]]:
        return self._all(kb_version, "interpretations")

    def provision_map(self, kb_version: str) -> dict[str, dict[str, Any]]:
        return self._cached(
            (kb_version, "provision_map"), lambda: {p["id"]: p for p in self.provisions(kb_version)}
        )

    def interpretation_map(self, kb_version: str) -> dict[str, dict[str, Any]]:
        return self._cached(
            (kb_version, "interpretation_map"),
            lambda: {p["id"]: p for p in self.interpretations(kb_version)},
        )

    def requirements(self, kb_version: str) -> list[dict[str, Any]]:
        return self._cached(
            (kb_version, "requirements"), lambda: self._read_yaml(kb_version, "requirements.yaml")
        )

    def test_templates(self, kb_version: str) -> list[dict[str, Any]]:
        return self._cached(
            (kb_version, "test_templates"),
            lambda: self._read_yaml(kb_version, "test_templates.yaml"),
        )
