"""Strip a background-task notification the model echoed into its answer.

A wake-up run's input is the task notification (a HumanMessage: a "not from
the user" note, a ``<task-notification>`` block with the raw result, and a
"Use the result to continue" trailer). Results pulled into a busy run arrive
the same way. Some models (Gemini Flash Lite) copy those blocks verbatim into
their reply before answering. The prompt forbids it; this is the deterministic
guard: the persisted answer keeps only the agent's own words.
"""

from __future__ import annotations

import re

_PREAMBLE = r"An async subagent task you started has an update\.[^\n]*"
_TRAILER = r"Use the result to continue;[^\n]*"

#: One echoed notification: an optional preamble, the tagged block (closed, or
#: cut off at the end of the text) and an optional trailer.
_ECHO = re.compile(
    rf"(?:{_PREAMBLE}\s*)?<task-notification>[\s\S]*?(?:</task-notification>|$)\s*(?:{_TRAILER}\s*)?"
)
#: A preamble or trailer left on its own line.
_STRAY = re.compile(rf"^[ \t]*(?:{_PREAMBLE}|{_TRAILER})[ \t]*\n?", re.MULTILINE)


def strip_notification_echo(text: str) -> str:
    """``text`` without echoed task notifications (unchanged when there are none)."""
    if "<task-notification>" not in text and "An async subagent task" not in text:
        return text
    cleaned = _STRAY.sub("", _ECHO.sub("", text))
    return cleaned.strip()
