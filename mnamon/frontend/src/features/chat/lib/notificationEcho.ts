/**
 * A background-task notification the model echoed into its answer, removed for display.
 *
 * A wake-up's input (and a result pulled into a busy run) is the notification: a "not from the
 * user" note, a `<task-notification>` block with the raw result and a "Use the result to
 * continue" line. Some models copy those blocks into their reply before answering. The backend
 * strips them from the stored text (`utils/notification_echo.py`); this does the same for the
 * streamed blocks, so the raw notification never reads as the agent's words.
 */
const PREAMBLE = String.raw`An async subagent task you started has an update\.[^\n]*`;
const TRAILER = String.raw`Use the result to continue;[^\n]*`;
const ECHO = new RegExp(
  String.raw`(?:${PREAMBLE}\s*)?<task-notification>[\s\S]*?(?:</task-notification>|$)\s*(?:${TRAILER}\s*)?`,
  'g',
);
const STRAY = new RegExp(String.raw`^[ \t]*(?:${PREAMBLE}|${TRAILER})[ \t]*\n?`, 'gm');
/** The start of the preamble, still streaming in at the very end of the text. */
const PARTIAL = 'An async subagent task you started has an update.';

export function stripNotificationEcho(text: string): string {
  if (!text.includes('<task-notification>') && !text.includes('An async subagent task')) {
    const tail = text.trimStart();
    // Mid-stream, before the tag arrives: hold back a reply that so far is only the preamble.
    return tail.length && PARTIAL.startsWith(tail) && tail.length >= 8 ? '' : text;
  }
  return text.replace(ECHO, '').replace(STRAY, '').trim();
}
