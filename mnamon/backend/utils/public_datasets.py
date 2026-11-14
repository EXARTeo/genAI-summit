"""Public reference datasets in a system folder (``datasets/public/<slug>/``).

The one place the agents service may write a system folder: a human-approved
public dataset (``public_dataset_candidates`` artifact) fetched by the agent's
``fetch_public_dataset`` tool. Only these file names, only under that prefix.
"""

import re

from fastapi import HTTPException, status

from utils.workspace import normalize_path

PUBLIC_DATASETS_PREFIX = "datasets/public"
ALLOWED_FILES = frozenset({"data.csv", "datasheet.md", "mapping.yaml", "source.json"})
_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")


def public_dataset_path(slug: str, name: str) -> str:
    """``datasets/public/<slug>/<name>``; 400 for anything else."""
    if not _SLUG.fullmatch(slug or "") or name not in ALLOWED_FILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only {sorted(ALLOWED_FILES)} under {PUBLIC_DATASETS_PREFIX}/<slug>/.",
        )
    return normalize_path(f"{PUBLIC_DATASETS_PREFIX}/{slug}/{name}")
