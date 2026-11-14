"""Agent tool: hand a finished file to the user as a deliverable.

The single explicit act that promotes a document out of the agent's working
files into something the user receives. Everything an agent (or its
sub-agents) writes to ``/conversation/output/`` stays invisible; only a file
passed to ``present_artifact`` is surfaced, as a card at the point of the call
and, once the run ends, as a generated attachment of the answer.

The tool reads the file's bytes when it is called and parks them in the run's
:class:`PresentedFiles`, keyed by the tool call. The tool result the model
reads stays a short confirmation (the bytes never enter the context or the
checkpoint); the stream normalizer turns the call's successful result into the
``PRESENT_ARTIFACT`` event and attaches the parked bytes as ``data_base64``
(orchestrator only: a sub-agent's file is scratch until the orchestrator
presents it). The backend stores those bytes as the attachment, so a file
changed after it was presented never changes what the user received.

Bound **per run** to the run's conversation files, so it can only ever reach
this conversation's output folder.
"""

from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Annotated

from langchain_core.tools import InjectedToolCallId, StructuredTool
from pydantic import BaseModel, Field

from core.logging import get_logger
from core.settings import settings
from harness.conversation_files import ConversationFiles
from harness.conversation_files.paths import OUTPUT_PREFIX, InvalidPath, normalise

logger = get_logger(__name__)

PRESENT_ARTIFACT_TOOL_NAME = "present_artifact"

_MAX_TITLE = 120
_MAX_SUMMARY = 300


@dataclass(frozen=True)
class PresentedFile:
    """One accepted presentation: the card's fields and, when within the caps, its bytes."""

    path: str
    filename: str
    title: str
    summary: str | None
    mime: str
    size: int
    data_base64: str | None


class PresentedFiles:
    """One run's accepted presentations, by tool call id, until the stream emits them.

    Shared by the run's ``present_artifact`` tool (which fills it) and its
    stream normalizer (which drains it). Counts what it has handed out so the
    run never ships more than ``OUTPUT_MAX_FILES`` files' bytes.
    """

    def __init__(self) -> None:
        self._by_call: dict[str, PresentedFile] = {}
        self._with_bytes = 0

    def admits_bytes(self, size: int) -> bool:
        """Whether a file of ``size`` bytes may still ride its event."""
        return (
            size <= settings.filesystem.output_max_file_bytes
            and self._with_bytes < settings.filesystem.output_max_files
        )

    def put(self, call_id: str, presented: PresentedFile) -> None:
        """Park one accepted presentation until the stream emits its card."""
        if presented.data_base64 is not None:
            self._with_bytes += 1
        self._by_call[call_id] = presented

    def pop(self, call_id: str) -> PresentedFile | None:
        """Take the presentation of one call, or None when the tool refused it."""
        return self._by_call.pop(call_id, None)


class _PresentArtifactArgs(BaseModel):
    path: str = Field(
        description="Virtual path of the finished file to present, under "
        "'/conversation/output/' (e.g. '/conversation/output/q3_report.docx'). "
        "The file must already be written there."
    )
    title: str = Field(
        description="Short, human-friendly title for the deliverable shown to "
        "the user, e.g. 'Q3 Financial Report'."
    )
    summary: str = Field(
        default="",
        description="Optional one-line description of what the document contains.",
    )
    tool_call_id: Annotated[str, InjectedToolCallId]


def build_present_artifact_tool(
    *, files: ConversationFiles, presented: PresentedFiles
) -> StructuredTool:
    """Return a ``present_artifact`` tool bound to this run's conversation files."""

    async def _present_artifact(path: str, title: str, tool_call_id: str, summary: str = "") -> str:
        title = (title or "").strip()[:_MAX_TITLE]
        if not title:
            return "Could not present: 'title' is required."
        # A path outside output/ (or with an illegal segment) is an error the
        # model should fix, never a silent no-op.
        try:
            resolved = normalise((path or "").strip())
        except InvalidPath as exc:
            return f"Could not present: {exc}"
        if not resolved.startswith(OUTPUT_PREFIX):
            return f"Could not present: artifact path must be under {OUTPUT_PREFIX}: {path!r}"
        data = await files.read_bytes(resolved)
        if data is None:
            return (
                f"Could not present: no file at {path!r}. Write the document to "
                f"'{OUTPUT_PREFIX}' first, then present it."
            )
        filename = PurePosixPath(resolved).name
        with_bytes = presented.admits_bytes(len(data))
        presented.put(
            tool_call_id,
            PresentedFile(
                path=resolved,
                filename=filename,
                title=title,
                summary=(summary or "").strip()[:_MAX_SUMMARY] or None,
                mime=mimetypes.guess_type(filename)[0] or "application/octet-stream",
                size=len(data),
                data_base64=base64.b64encode(data).decode("ascii") if with_bytes else None,
            ),
        )
        logger.info(
            "artifact_presented",
            "Agent presented an output file as a deliverable",
            agent_slug=files.agent_slug,
            conversation_id=files.conversation_id,
            bytes=len(data),
            with_bytes=with_bytes,
        )
        return (
            f"'{title}' is now a document card in the conversation, which the "
            "user can open or download. Carry on in the same reply: whatever "
            "you write next appears below the card. Do not paste the document's "
            "contents into the chat."
        )

    return StructuredTool.from_function(
        coroutine=_present_artifact,
        name=PRESENT_ARTIFACT_TOOL_NAME,
        description=(
            "Hand a finished document to the user, right where you are in the "
            "reply. The moment you call this, a document card appears in the "
            "conversation at that point; the user can preview or download it, "
            "and anything you write afterwards continues below it. Use it "
            "mid-answer, as you go: hand over each document as it becomes "
            "ready and keep talking around it. A file written to "
            "'/conversation/output/' stays invisible until you present it, so "
            "write it there first. Present as many separate documents as you "
            "genuinely produced (each gets its own card), but present a given "
            "file once, and only when it is finished: never scratch notes, "
            "intermediate drafts or helper files. Provide the file 'path', a "
            "short 'title', and an optional one-line 'summary' shown on the card."
        ),
        args_schema=_PresentArtifactArgs,
    )
