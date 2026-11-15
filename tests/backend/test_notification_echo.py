"""The guard that strips task notifications a model echoed into its answer."""

from __future__ import annotations

from utils.notification_echo import strip_notification_echo

NOTICE = (
    "An async subagent task you started has an update. This is not a message from the "
    "user: don't treat it as their answer to any question.\n\n"
    "<task-notification>\n<task-id>t-1</task-id>\n<agent-name>general-purpose</agent-name>\n"
    "<status>success</status>\n<result>\n## State of SYS-003\n- fine\n</result>\n"
    "</task-notification>\n"
    "Use the result to continue; report back to the user if they're waiting on it.\n"
)


def test_plain_answer_is_untouched() -> None:
    text = "All four systems are described below.\n\n- SYS-001: biased"
    assert strip_notification_echo(text) == text


def test_echoed_notifications_are_removed() -> None:
    text = NOTICE + NOTICE.replace("t-1", "t-2") + "All four subagents finished. Summary: ok."
    assert strip_notification_echo(text) == "All four subagents finished. Summary: ok."


def test_unterminated_echo_is_cut_to_the_end() -> None:
    text = "Intro.\n\n" + NOTICE.split("</result>")[0]
    assert strip_notification_echo(text) == "Intro."


def test_stray_preamble_line_is_removed() -> None:
    text = (
        "An async subagent task you started has an update. This is not a message.\n"
        "Here is what it found."
    )
    assert strip_notification_echo(text) == "Here is what it found."
