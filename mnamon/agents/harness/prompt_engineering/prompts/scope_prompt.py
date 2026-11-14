"""The conversation's scope: which system (and audit) the user opened this chat from.

A chat started from "Chat about this system" or "Chat about this audit" carries
``system_id`` (and ``audit_id``) in the run context. This section is the
``<user_context>`` layer of the prompt: it tells the agent what the user is
looking at, so it starts there and says so. Empty for an unscoped chat. It
comes after the platform defaults and before the memory index and the date.
"""

from __future__ import annotations

from harness.prompt_engineering.context import PromptContext


def scope_prompt(context: PromptContext) -> str:
    """The scope block for this run. Empty when the conversation is not scoped."""
    system_id = context.scope_system_id
    if not system_id:
        return ""
    audit_id = context.scope_audit_id
    target = f"system `{system_id}`" + (f", audit `{audit_id}`" if audit_id else "")
    first = (
        "that audit's status and artifacts (findings, critic, reports) and the system's card"
        if audit_id
        else "that system's folder (system card, plugins, evidence, gaps) and its audits"
    )
    return (
        "<user_context>\n"
        f"The user opened this conversation from {target}. Unless they ask about something "
        f"else, start from {first}, and open your first answer by saying what you are "
        "scoped to.\n"
        "</user_context>"
    )


__all__ = ["scope_prompt"]
