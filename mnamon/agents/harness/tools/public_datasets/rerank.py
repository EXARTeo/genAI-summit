"""Optional Gemini pass over the ranked candidates (only when ``GOOGLE_API_KEY`` is set).

It never replaces the deterministic score: it adds ``llm_rank`` per candidate and
a one-line note on fit, licence and bias risks, shown next to the score at the
HITL pick. Any error -> ``{"used": False, "error": ...}``; the search still works.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from harness.tools.public_datasets.models import SystemContext

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PROMPT = """You review public datasets proposed as a reference for synthetic test data
for an AI system audit. System: {name} ({plugin}). Purpose: {purpose}
Our fields: {fields}. Protected: {protected}. Label: {labels}.
Candidates (deterministic score already computed):
{candidates}
Return JSON {{"order": [candidate ids, best first], "notes": {{id: "one sentence on fit,
licence and known bias risks"}}}}. Use only the ids given."""


def rerank_with_gemini(
    ctx: SystemContext,
    ranked: list[dict[str, Any]],
    *,
    client: httpx.Client,
    api_key: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    key = api_key if api_key is not None else os.environ.get("GOOGLE_API_KEY", "")
    if not key or not ranked:
        return {"used": False}
    model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    brief = [
        {
            "id": c["id"],
            "name": c["name"],
            "score": c["score"],
            "mapped": sorted(c["mapping"]),
            "gaps": c["gaps"],
            "licence": c["licence"]["normalised"],
            "rows": c["n_rows"],
            "description": c["description"][:300],
        }
        for c in ranked[:8]
    ]
    prompt = PROMPT.format(
        name=ctx.name,
        plugin=ctx.plugin,
        purpose=ctx.purpose[:400],
        fields=", ".join(ctx.model_fields),
        protected=", ".join(ctx.protected + ctx.proxies),
        labels=", ".join(ctx.label_names),
        candidates=json.dumps(brief),
    )
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    try:
        response = client.post(
            GEMINI_URL.format(model=model), json=body, headers={"x-goog-api-key": key}
        )
        response.raise_for_status()
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        return {"used": False, "error": f"{type(exc).__name__}"}
    ids = {c["id"] for c in ranked}
    order = [i for i in parsed.get("order") or [] if i in ids]
    notes = {k: str(v)[:400] for k, v in (parsed.get("notes") or {}).items() if k in ids}
    for c in ranked:
        c["llm_rank"] = order.index(c["id"]) + 1 if c["id"] in order else None
        if c["id"] in notes:
            c["llm_note"] = notes[c["id"]]
    return {"used": True, "model": model, "order": order, "notes": notes}
