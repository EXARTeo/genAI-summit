"""The classifier's regulation tools, pinned to the run's ``kb_version``.

* ``lookup_provision(provision_id)``: verbatim text, children, related guidance ids.
* ``search_regulation(query)``: reg-memory's ranked search (``/v1/provisions/search``).
* ``read_guidance(interpretation_id, query)``: the paragraphs of one guidance
  node that match the query (deterministic keyword windows, at most ~4,000
  characters) with ``binding`` / ``status``: guidance PDFs are one node of
  100+ pages, so the whole text never goes to the model.

Every lookup lands in the run's :class:`KbCache` (the verifier reuses it). A
tool never raises: an error comes back to the agent as text.
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pipeline.clients import PipelineHTTPError, RegMemory
from pipeline.steps import safe_tool
from pydantic import BaseModel, Field

from classification.prechecks import KbCache

#: Longest excerpt ``read_guidance`` returns.
GUIDANCE_EXCERPT_CHARS = 4_000
_WINDOW = 1_000
_WORD = re.compile(r"[a-z0-9]{3,}")


def _dump(value: Any, limit: int = 12_000) -> str:
    text = json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + f"\n... [{len(text) - limit} more]"


def _windows(text: str) -> list[str]:
    """Paragraphs of ``text``; a long one is cut into ~1,000-character windows."""
    out: list[str] = []
    for raw in re.split(r"\n\s*\n", text):
        para = raw.strip()
        while len(para) > _WINDOW * 1.2:
            cut = para.rfind(" ", 0, _WINDOW)
            cut = cut if cut > _WINDOW // 2 else _WINDOW
            out.append(para[:cut].strip())
            para = para[cut:].strip()
        if para:
            out.append(para)
    return out


def guidance_excerpt(
    text: str, query: str, limit: int = GUIDANCE_EXCERPT_CHARS
) -> tuple[str, list[str]]:
    """The paragraphs of ``text`` that best match ``query``, in document order, max ``limit``.

    A paragraph scores by the distinct query words it holds, then by their hits;
    the best are kept until the limit. No match: the start of the text.
    """
    terms = sorted(set(_WORD.findall(query.lower())))
    windows = _windows(text or "")
    scored: list[tuple[float, int]] = []
    for i, window in enumerate(windows):
        low = window.lower()
        present = [t for t in terms if t in low]
        if present:
            scored.append((len(present) + 0.01 * sum(low.count(t) for t in present), i))
    matched = sorted({t for t in terms if any(t in w.lower() for w in windows)})
    order = [i for _, i in sorted(scored, key=lambda x: (-x[0], x[1]))] or list(range(len(windows)))
    picked: list[int] = []
    used = 0
    for i in order:
        size = len(windows[i]) + 7
        if used + size > limit:
            if not picked:
                picked.append(i)
            break
        picked.append(i)
        used += size
    return "\n[...]\n".join(windows[i][:limit] for i in sorted(picked)), matched


class _ProvisionArgs(BaseModel):
    provision_id: str = Field(description="e.g. AIA.6.3 or AIA.ANNEX_III.4.a")


class _SearchArgs(BaseModel):
    query: str = Field(description="Words to find in the regulation text.")


class _GuidanceArgs(BaseModel):
    interpretation_id: str = Field(description="A guidance id (INT....) from the brief or lookup.")
    query: str = Field(description="Words to find in it, e.g. 'narrow procedural task CV'.")


def _ids(items: Any, limit: int) -> list[Any]:
    out: list[Any] = []
    for item in (items if isinstance(items, list) else [])[:limit]:
        out.append(item.get("id") if isinstance(item, dict) else str(item))
    return out


def regulation_tools(regmem: RegMemory, kb: KbCache) -> list[BaseTool]:
    version = kb.kb_version

    @safe_tool("lookup_provision")
    async def lookup_provision(provision_id: str) -> str:
        try:
            body = await regmem.provision(provision_id, version)
        except PipelineHTTPError as exc:
            if exc.status == 404:
                kb.nodes[provision_id] = None
            return f"Could not read {provision_id}: {exc.public}."
        if not isinstance(body, dict) or not body.get("id"):
            return f"{provision_id}: no such provision at kb_version {version}."
        kb.nodes[provision_id] = body
        keep = {k: body.get(k) for k in ("id", "title", "text", "kb_version")}
        keep["children"] = _ids(body.get("children"), 40)
        keep["interpretations"] = _ids(body.get("interpretations"), 10)
        return _dump(keep)

    @safe_tool("search_regulation")
    async def search_regulation(query: str) -> str:
        try:
            items = await regmem.search(query, kb_version=version, limit=10)
        except PipelineHTTPError as exc:
            return f"Search failed: {exc.public}."
        keys = ("id", "label", "title", "snippet", "binding")
        rows = [
            {k: i.get(k) for k in keys if i.get(k) is not None}
            for i in items
            if isinstance(i, dict)
        ]
        return _dump(rows)

    @safe_tool("read_guidance")
    async def read_guidance(interpretation_id: str, query: str) -> str:
        try:
            body = await regmem.interpretation(interpretation_id, version)
        except PipelineHTTPError as exc:
            if exc.status == 404:
                kb.nodes[interpretation_id] = None
            return f"Could not read {interpretation_id}: {exc.public}."
        if not isinstance(body, dict) or not body.get("id"):
            return f"{interpretation_id}: no such guidance at kb_version {version}."
        kb.nodes[interpretation_id] = {k: v for k, v in body.items() if k != "text"}
        excerpt, matched = guidance_excerpt(str(body.get("text") or ""), query)
        keep = {k: body.get(k) for k in ("id", "title", "source_id", "binding", "status")}
        keep["kb_version"] = body.get("kb_version") or version
        keep["matched_terms"] = matched
        keep["excerpt"] = excerpt
        return _dump(keep, GUIDANCE_EXCERPT_CHARS + 1_000)

    return [
        StructuredTool.from_function(
            coroutine=lookup_provision,
            name="lookup_provision",
            description=f"Verbatim text of one provision at kb_version {version}, with its "
            "children and the ids of the guidance that relates to it.",
            args_schema=_ProvisionArgs,
        ),
        StructuredTool.from_function(
            coroutine=search_regulation,
            name="search_regulation",
            description="Find provisions by words, ranked (ids, titles, snippets).",
            args_schema=_SearchArgs,
        ),
        StructuredTool.from_function(
            coroutine=read_guidance,
            name="read_guidance",
            description="Read the paragraphs of one guidance document (INT.*, non-binding) "
            "that match your words.",
            args_schema=_GuidanceArgs,
        ),
    ]


__all__ = ["GUIDANCE_EXCERPT_CHARS", "guidance_excerpt", "regulation_tools"]
