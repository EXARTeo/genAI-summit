"""Extraction stage: raw version -> text, incremental.

A version is extracted once (``processed.extracted`` + the text file exist);
``--force`` redoes it. Run on its own:

    python -m engine.extract.stage [--source SOURCE_ID ...] [--force]
"""

from __future__ import annotations

import argparse
from typing import Any

from core.logging import configure_logging, get_logger
from core.settings import settings
from engine.extract.text import extract_text
from engine.store import Store

logger = get_logger(__name__)


def extract_pending(
    store: Store, source_ids: list[str] | None = None, *, force: bool = False
) -> dict[str, int]:
    counts = {"extracted": 0, "skipped": 0, "failed": 0}
    for manifest in store.list_manifests():
        if source_ids and manifest.get("source_id") not in source_ids:
            continue
        dirty = False
        for entry in store.content_versions(manifest):
            done = entry.get("processed", {}).get("extracted") and entry.get("text_path")
            if done and not force and store.abs(entry["text_path"]).exists():
                counts["skipped"] += 1
                continue
            dirty = True
            _extract_one(store, manifest["doc_id"], entry, counts)
        if dirty:
            store.save_manifest(manifest)
    return counts


def _extract_one(store: Store, doc_id: str, entry: dict[str, Any], counts: dict) -> None:
    processed = entry.setdefault("processed", {})
    try:
        text = extract_text(store.abs(entry["raw_path"]).read_bytes(), entry.get("ext") or "bin")
    except Exception as exc:  # one bad file must not stop the stage
        processed["extracted"] = False
        entry["extract_error"] = f"{type(exc).__name__}: {exc}"
        counts["failed"] += 1
        logger.warning("extract_failed", "Text extraction failed", doc_id=doc_id, error=str(exc))
        return
    path = store.text_path_for(doc_id, entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    entry["text_path"] = store.rel(path)
    entry["text_chars"] = len(text)
    entry.pop("extract_error", None)
    processed["extracted"] = True
    counts["extracted"] += 1


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", dest="sources")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    configure_logging()
    print(extract_pending(Store(settings.store.data_dir), args.sources, force=args.force))  # noqa: T201


if __name__ == "__main__":
    main()
