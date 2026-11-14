"""Public dataset discovery: find, score and fetch public datasets that match a
system's data dictionary, before any synthetic data is generated.

Runs in the agents service (it has internet; the sandbox does not). Pure Python
+ httpx, no LLM inside except the optional Gemini re-rank. Flow:
``search_public_datasets`` -> ``public_dataset_candidates`` artifact (HITL pick)
-> ``fetch_public_dataset`` -> ``datasets/public/<slug>/`` -> synthkit
``generation.mode: reference_sample``. Docs: docs/architecture/synthetic-data.md.
"""

from harness.tools.public_datasets.context import build_queries, load_contexts, read_system_dir
from harness.tools.public_datasets.fetch import (
    BackendStore,
    LocalStore,
    fetch_from_result,
    fetch_public_dataset,
    find_pii_columns,
)
from harness.tools.public_datasets.models import Candidate, Column, Field, SystemContext
from harness.tools.public_datasets.scoring import licence_status, rank, score_candidate
from harness.tools.public_datasets.search import (
    ARTIFACT_KIND,
    search_public_datasets,
    to_markdown,
    write_report,
)
from harness.tools.public_datasets.tools import (
    InternalAPI,
    build_public_dataset_tools,
    run_fetch,
    run_search,
)

__all__ = [
    "ARTIFACT_KIND",
    "BackendStore",
    "Candidate",
    "Column",
    "Field",
    "InternalAPI",
    "LocalStore",
    "SystemContext",
    "build_public_dataset_tools",
    "build_queries",
    "fetch_from_result",
    "fetch_public_dataset",
    "find_pii_columns",
    "licence_status",
    "load_contexts",
    "rank",
    "read_system_dir",
    "run_fetch",
    "run_search",
    "score_candidate",
    "search_public_datasets",
    "to_markdown",
    "write_report",
]
