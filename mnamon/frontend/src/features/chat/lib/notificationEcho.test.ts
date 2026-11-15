import { describe, expect, it } from 'vitest';
import { stripNotificationEcho } from './notificationEcho';

const NOTICE =
  "An async subagent task you started has an update. This is not a message from the user: don't treat it as their answer to any question.\n\n" +
  '<task-notification>\n<task-id>t-1</task-id>\n<agent-name>general-purpose</agent-name>\n<status>success</status>\n' +
  '<result>\n## State of SYS-003\n- fine\n</result>\n</task-notification>\n' +
  "Use the result to continue; report back to the user if they're waiting on it.\n";

describe('stripNotificationEcho', () => {
  it('leaves an ordinary answer alone', () => {
    const text = 'All four systems:\n\n- SYS-001: biased';
    expect(stripNotificationEcho(text)).toBe(text);
  });

  it('removes every echoed notification and keeps the answer', () => {
    const text = NOTICE + NOTICE.replace('t-1', 't-2') + 'All four subagents finished.';
    expect(stripNotificationEcho(text)).toBe('All four subagents finished.');
  });

  it('hides a notification that is still streaming in', () => {
    expect(stripNotificationEcho(NOTICE.slice(0, 220))).toBe('');
    expect(stripNotificationEcho('An async subagent')).toBe('');
  });
});
