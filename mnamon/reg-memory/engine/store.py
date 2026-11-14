"""The versioned document store: one directory (the ``/data`` volume).

    <data>/
      catalog/<run_id>.yaml                       catalog snapshot used by a run
      raw/<doc_id>/v0001__<sha12>.<ext>           original bytes, never overwritten
      text/<doc_id>/v0001__<sha12>.md             extracted text, one per raw version
      diffs/<doc_id>/v0001__v0002.diff (+ .json)  text diff between consecutive versions
      manifests/<doc_id>.json                     append-only fetch log + per-stage flags
      runs/<run_id>.json                          one ingest run

A *document* is one fetched artifact: a source's main text (``doc_id`` = the
source id), another format of it (``<source_id>.pdf``) or a linked child
(``<source_id>.<slug>``, with ``parent_id``). Same bytes => status ``same``
and no new file.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DOC_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def vtag(version: int) -> str:
    return f"v{version:04d}"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class Store:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ---- paths ----------------------------------------------------------------

    def _dir(self, name: str) -> Path:
        return self.root / name

    def _check(self, doc_id: str) -> str:
        if not DOC_ID_RE.match(doc_id):
            raise ValueError(f"invalid doc id: {doc_id!r}")
        return doc_id

    def manifest_path(self, doc_id: str) -> Path:
        return self._dir("manifests") / f"{self._check(doc_id)}.json"

    def abs(self, rel: str) -> Path:
        return self.root / rel

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    # ---- manifests --------------------------------------------------------------

    def load_manifest(self, doc_id: str) -> dict[str, Any] | None:
        path = self.manifest_path(doc_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_manifest(self, manifest: dict[str, Any]) -> None:
        data = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
        _atomic_write(self.manifest_path(manifest["doc_id"]), data)

    def list_manifests(self) -> list[dict[str, Any]]:
        folder = self._dir("manifests")
        if not folder.exists():
            return []
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))]

    def is_empty(self) -> bool:
        folder = self._dir("manifests")
        return not folder.exists() or not any(folder.glob("*.json"))

    @staticmethod
    def content_versions(manifest: dict[str, Any]) -> list[dict[str, Any]]:
        """Entries that introduced new bytes (status new/changed), oldest first."""
        return [v for v in manifest.get("versions", []) if v.get("raw_path")]

    def latest(self, manifest: dict[str, Any]) -> dict[str, Any] | None:
        versions = self.content_versions(manifest)
        return versions[-1] if versions else None

    # ---- recording a fetch --------------------------------------------------------

    def record(
        self,
        *,
        doc_id: str,
        source_id: str,
        url: str,
        parent_id: str | None = None,
        label: str | None = None,
        content: bytes | None = None,
        ext: str | None = None,
        final_url: str | None = None,
        content_type: str | None = None,
        filename: str | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        not_modified: bool = False,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Append one fetch to the document's manifest; write raw bytes only if new."""
        manifest = self.load_manifest(doc_id) or {
            "doc_id": doc_id,
            "source_id": source_id,
            "parent_id": parent_id,
            "url": url,
            "label": label,
            "versions": [],
        }
        if label:
            manifest["label"] = label
        latest = self.latest(manifest)
        entry: dict[str, Any] = {
            "version": latest["version"] if latest else None,
            "fetched_at": now_iso(),
            "url": url,
            "final_url": final_url or url,
            "sha256": latest["sha256"] if latest else None,
            "content_type": content_type,
            "bytes": latest["bytes"] if latest else 0,
            "status": "same",
        }
        if parent_id:
            entry["parent_id"] = parent_id
        if error is not None:
            entry.update(status="failed", error=error, bytes=0)
        elif not_modified:
            pass  # HTTP 304: same as the latest version, nothing downloaded
        else:
            assert content is not None  # noqa: S101 - internal contract
            sha = hashlib.sha256(content).hexdigest()
            if not latest or latest["sha256"] != sha:
                version = (latest["version"] + 1) if latest else 1
                raw = self._dir("raw") / doc_id / f"{vtag(version)}__{sha[:12]}.{ext or 'bin'}"
                if not raw.exists():
                    _atomic_write(raw, content)
                entry.update(
                    version=version,
                    sha256=sha,
                    bytes=len(content),
                    status="changed" if latest else "new",
                    raw_path=self.rel(raw),
                    ext=ext,
                    filename=filename,
                    processed={"extracted": False, "diffed": False},
                )
            if etag or last_modified:
                manifest["etag"], manifest["last_modified"] = etag, last_modified
        manifest["versions"].append(entry)
        manifest["updated_at"] = entry["fetched_at"]
        self.save_manifest(manifest)
        return entry

    def latest_raw(self, doc_id: str) -> tuple[bytes, dict[str, Any]] | None:
        manifest = self.load_manifest(doc_id)
        latest = self.latest(manifest) if manifest else None
        if not latest:
            return None
        return self.abs(latest["raw_path"]).read_bytes(), latest

    # ---- text ---------------------------------------------------------------------

    def text_path_for(self, doc_id: str, entry: dict[str, Any]) -> Path:
        return self._dir("text") / doc_id / f"{vtag(entry['version'])}__{entry['sha256'][:12]}.md"

    def read_text(self, doc_id: str, version: int | None = None) -> tuple[str, dict] | None:
        manifest = self.load_manifest(doc_id)
        if not manifest:
            return None
        versions = self.content_versions(manifest)
        if version is not None:
            versions = [v for v in versions if v["version"] == version]
        for entry in reversed(versions):
            if entry.get("text_path") and self.abs(entry["text_path"]).exists():
                return self.abs(entry["text_path"]).read_text(encoding="utf-8"), entry
        return None

    # ---- runs and catalog snapshots -----------------------------------------------

    def save_run(self, run: dict[str, Any]) -> None:
        path = self._dir("runs") / f"{run['run_id']}.json"
        _atomic_write(path, json.dumps(run, indent=2, ensure_ascii=False).encode("utf-8"))

    def load_run(self, run_id: str) -> dict[str, Any] | None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
            return None
        path = self._dir("runs") / f"{run_id}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def snapshot_catalog(self, run_id: str, catalog_path: Path) -> str:
        dest = self._dir("catalog") / f"{run_id}.yaml"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(catalog_path, dest)
        return self.rel(dest)
