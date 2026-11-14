"""Diff stage: text of consecutive versions -> unified diff + JSON summary.

Incremental: a pair is diffed once (the ``.diff`` file exists); the first
version has nothing to diff against. Run on its own:

    python -m engine.diff [--source SOURCE_ID ...] [--force]

``--source`` matches a source id and all its documents (other formats, children).
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
from typing import Any

from core.logging import configure_logging
from core.settings import settings
from engine.store import Store, now_iso, vtag

# Lines that open a section: markdown headings and EU-law structure lines.
_SECTION = re.compile(r"^(#{1,6}\s+.+|(Article|ANNEX|CHAPTER|SECTION|TITLE)\s+[0-9IVXLC]+\b.*)")


def _section_index(lines: list[str]) -> list[str | None]:
    current: str | None = None
    out: list[str | None] = []
    for line in lines:
        if _SECTION.match(line.strip()):
            current = line.strip().lstrip("#").strip()[:120]
        out.append(current)
    return out


def diff_texts(old: str, new: str, from_label: str, to_label: str) -> tuple[str, dict[str, Any]]:
    a, b = old.splitlines(), new.splitlines()
    unified = "\n".join(
        difflib.unified_diff(a, b, fromfile=from_label, tofile=to_label, lineterm="", n=2)
    )
    sections_b, sections_a = _section_index(b), _section_index(a)
    added = removed = 0
    changed: list[str] = []
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        added += j2 - j1
        removed += i2 - i1
        section = (sections_b[j1] if j1 < len(b) else None) or (
            sections_a[i1] if i1 < len(a) else None
        )
        if section and section not in changed:
            changed.append(section)
    summary = {
        "from": from_label,
        "to": to_label,
        "lines_added": added,
        "lines_removed": removed,
        "changed_sections": changed,
        "created_at": now_iso(),
    }
    return unified + ("\n" if unified else ""), summary


def diff_pending(
    store: Store, source_ids: list[str] | None = None, *, force: bool = False
) -> dict[str, int]:
    counts = {"diffed": 0, "skipped": 0, "waiting": 0}
    for manifest in store.list_manifests():
        if source_ids and manifest.get("source_id") not in source_ids:
            continue
        doc_id = manifest["doc_id"]
        versions = store.content_versions(manifest)
        dirty = False
        for idx, entry in enumerate(versions):
            processed = entry.setdefault("processed", {})
            if idx == 0:
                if not processed.get("diffed"):
                    processed["diffed"], dirty = True, True  # nothing to diff against
                continue
            prev = versions[idx - 1]
            name = f"{vtag(prev['version'])}__{vtag(entry['version'])}"
            diff_path = store.abs(f"diffs/{doc_id}/{name}.diff")
            if diff_path.exists() and not force:
                counts["skipped"] += 1
                if not processed.get("diffed"):
                    processed["diffed"], dirty = True, True
                continue
            old, new = prev.get("text_path"), entry.get("text_path")
            if not (old and new and store.abs(old).exists() and store.abs(new).exists()):
                counts["waiting"] += 1  # extract first
                continue
            unified, summary = diff_texts(
                store.abs(old).read_text(encoding="utf-8"),
                store.abs(new).read_text(encoding="utf-8"),
                vtag(prev["version"]),
                vtag(entry["version"]),
            )
            summary["doc_id"] = doc_id
            diff_path.parent.mkdir(parents=True, exist_ok=True)
            diff_path.write_text(unified, encoding="utf-8")
            diff_path.with_suffix(".json").write_text(
                json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            entry["diff_path"] = store.rel(diff_path)
            processed["diffed"], dirty = True, True
            counts["diffed"] += 1
        if dirty:
            store.save_manifest(manifest)
    return counts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", dest="sources")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    configure_logging()
    print(diff_pending(Store(settings.store.data_dir), args.sources, force=args.force))  # noqa: T201


if __name__ == "__main__":
    main()
