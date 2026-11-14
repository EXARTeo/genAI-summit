"""The audit pipeline's state: plain JSON-like values only.

The state is checkpointed (Postgres, strict msgpack), so it holds dicts, lists
and strings, never pydantic objects. Maps that several nodes add to merge
instead of being replaced.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict


def merge(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """Reducer: a node's update is merged into the map (``None`` value = delete)."""
    out = dict(left or {})
    for key, value in (right or {}).items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


class AuditState(TypedDict, total=False):
    # Identity (from the run context; the model never sets them)
    audit_id: str
    system_id: str
    kb_version: str
    status: str
    # load_context
    card: dict[str, Any]
    target: str  # plugin id, e.g. SYS-001.cv-ranker
    plugin_dir: str  # plugins/<name>
    files: dict[str, str]  # input-relative path -> text (plugin.yaml, data/...)
    requirements: list[dict[str, Any]]
    templates: list[dict[str, Any]]
    # steps
    profile: dict[str, Any]
    public_data: dict[str, Any]
    scenarios: dict[str, Any]
    scenario_analysis: dict[str, Any]
    spec: dict[str, Any]
    dataset: dict[str, Any]
    dataset_analysis: dict[str, Any]
    test_plan: dict[str, Any]
    test_results: dict[str, Any]
    findings: list[dict[str, Any]]
    critic: dict[str, Any]
    report: dict[str, Any]
    # control
    artifacts: Annotated[dict[str, Any], merge]  # kind -> latest artifact id
    feedback: Annotated[dict[str, Any], merge]  # step -> {source, reason, category, attempt}
    redos: Annotated[dict[str, Any], merge]  # step -> human-requested redos
    auto_redos: Annotated[dict[str, Any], merge]  # step -> verifier-requested redos
    gates: Annotated[dict[str, Any], merge]  # gate -> last decision
    route: str  # the last router decision (redo | next | stop)
    stage_traces: Annotated[dict[str, Any], merge]  # stage -> Langfuse trace id


__all__ = ["AuditState", "merge"]
