"""Import the seed cases (``SEED_CASES_DIR``, default ``/seed-cases``) as systems.

Each top-level directory (``SYS-001/`` ...) becomes a system and its files the
``system:<id>`` namespace. ``_answer-key/`` directories (the expected findings,
for scoring only) and hidden files are never imported. Idempotent: a file whose
bytes did not change keeps its version (``put_file`` compares the sha256).
"""

import asyncio
import re
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import SystemTable
from schema.systems import SYSTEM_ID_PATTERN, SeedImportOut, SeedSystemResult
from utils.workspace import put_file, system_namespace

SEED_ACTOR = "seed"
SKIP_DIRS = frozenset({"_answer-key", "answer-keys", "__pycache__"})


def _card(system_dir: Path) -> dict[str, Any]:
    card_path = system_dir / "system-card.yaml"
    if not card_path.is_file():
        return {}
    try:
        loaded = yaml.safe_load(card_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _walk(system_dir: Path) -> list[tuple[str, bytes]]:
    """``(relative posix path, bytes)`` of every importable file, sorted."""
    files: list[tuple[str, bytes]] = []
    for path in sorted(system_dir.rglob("*")):
        rel = path.relative_to(system_dir)
        if any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts):
            continue
        if path.is_file():
            files.append((rel.as_posix(), path.read_bytes()))
    return files


def _name_from_card(card: dict[str, Any], fallback: str) -> str:
    for key in ("name", "system_name", "title"):
        value = card.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    system = card.get("system")
    if isinstance(system, dict) and isinstance(system.get("name"), str):
        return system["name"].strip()[:200] or fallback
    return fallback


async def import_seed(db: AsyncSession, root: str) -> SeedImportOut:
    """Import every system folder under ``root`` (flushed, not committed)."""
    root_path = Path(root)
    if not root_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Seed directory not found: {root}")
    # mlflow-seed exports <root>/systems/SYS-00X (and the answer keys beside it,
    # in <root>/answer-keys, which must never be imported).
    if (root_path / "systems").is_dir():
        root_path = root_path / "systems"
    results: list[SeedSystemResult] = []
    skipped: list[str] = []
    for system_dir in sorted(p for p in root_path.iterdir() if p.is_dir()):
        sid = system_dir.name
        if (
            sid in SKIP_DIRS
            or sid.startswith((".", "_"))
            or not re.fullmatch(SYSTEM_ID_PATTERN, sid)
            or not (system_dir / "system-card.yaml").is_file()
        ):
            skipped.append(sid)
            continue
        card = await asyncio.to_thread(_card, system_dir)
        files = await asyncio.to_thread(_walk, system_dir)
        system = await db.get(SystemTable, sid)
        created = system is None
        if system is None:
            system = SystemTable(
                id=sid,
                name=_name_from_card(card, sid),
                status="active",
                data={"source": "seed", "card": card},
            )
            db.add(system)
            await db.flush()
        else:
            system.name = _name_from_card(card, system.name)
            system.data = {**(system.data or {}), "source": "seed", "card": card}
        written = unchanged = 0
        for rel, content in files:
            _, changed = await put_file(
                db,
                namespace=system_namespace(sid),
                path=rel,
                content=content,
                actor=SEED_ACTOR,
                reason="seed import",
            )
            written += int(changed)
            unchanged += int(not changed)
        results.append(
            SeedSystemResult(
                id=sid, created=created, filesWritten=written, filesUnchanged=unchanged
            )
        )
    return SeedImportOut(root=str(root_path), systems=results, skippedDirs=skipped)
