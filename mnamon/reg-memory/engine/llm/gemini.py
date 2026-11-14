"""Google Gemini (``google-genai``), the only LLM of reg-memory.

Every caller has a deterministic fallback: :meth:`Gemini.json` returns ``None``
when no ``GOOGLE_API_KEY`` is set or the call fails, and the caller then uses
its heuristic. Tests replace :data:`client_factory` with a fake (no paid calls).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from google import genai
from google.genai import types

from core.logging import get_logger
from core.settings import LlmSettings, settings

logger = get_logger(__name__)


def _default_client(api_key: str) -> Any:
    return genai.Client(api_key=api_key)


#: api_key -> client with ``.aio.models.generate_content`` (swapped in tests).
client_factory: Callable[[str], Any] = _default_client


class Gemini:
    def __init__(self, cfg: LlmSettings | None = None) -> None:
        cfg = cfg or settings.llm
        self.api_key = cfg.google_api_key.get_secret_value()
        self.model = cfg.model
        self.max_items = cfg.max_items

    @property
    def active(self) -> bool:
        return bool(self.api_key)

    async def json(self, prompt: str, schema: dict[str, Any], *, purpose: str) -> Any | None:
        """Structured JSON answer for ``prompt`` (``schema`` = JSON Schema) or ``None``."""
        if not self.active:
            return None
        try:
            client = client_factory(self.api_key)
            resp = await client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=schema,
                    temperature=0,
                ),
            )
            data = json.loads(resp.text or "null")
            logger.info("llm_call", "Gemini call done", purpose=purpose, model=self.model)
            return data
        except Exception as exc:  # any SDK/network/parse error -> deterministic fallback
            logger.warning(
                "llm_call_failed",
                "Gemini call failed; using the fallback",
                purpose=purpose,
                error=type(exc).__name__,
            )
            return None
