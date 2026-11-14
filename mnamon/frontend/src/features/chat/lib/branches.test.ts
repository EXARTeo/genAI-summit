import { describe, expect, it } from 'vitest';
import { pathTo, selectionFor, selectSibling, siblingInfo, visiblePath } from './branches';
import { checkFiles, mimeOf, previewKind } from './attachments';
import { matchCommands, parseCommand } from './slashCommands';
import type { MessageOut } from './types';

const msg = (id: string, parent: string | null, at: number): MessageOut => ({
  id,
  parentMessageId: parent,
  sender: id.startsWith('u') ? 'user' : 'ai',
  content: id,
  attachments: [],
  rawEvents: [],
  created_at: new Date(at * 1000).toISOString(),
  updated_at: new Date(at * 1000).toISOString(),
});

// u1 → a1 (retried as a2) ; a1 → u2 → a3
const messages = [
  msg('u1', null, 1),
  msg('a1', 'u1', 2),
  msg('u2', 'a1', 3),
  msg('a3', 'u2', 4),
  msg('a2', 'u1', 5),
];

describe('branches', () => {
  it('shows the newest branch by default and follows a selection', () => {
    expect(visiblePath(messages).map((m) => m.id)).toEqual(['u1', 'a2']);
    const sel = selectionFor(messages, 'a3');
    expect(visiblePath(messages, sel).map((m) => m.id)).toEqual(['u1', 'a1', 'u2', 'a3']);
  });

  it('counts siblings and switches between them', () => {
    const a1 = messages[1];
    expect(siblingInfo(messages, a1)).toMatchObject({ index: 0, count: 2 });
    const sel = selectSibling(messages, a1, 1, {});
    expect(visiblePath(messages, sel).map((m) => m.id)).toEqual(['u1', 'a2']);
    expect(pathTo(messages, 'a3')).toEqual(['u1', 'a1', 'u2', 'a3']);
  });
});

describe('composer helpers', () => {
  it('guards attachments', () => {
    const f = (name: string, size: number) => new File([new Uint8Array(size)], name);
    expect(checkFiles([f('a.txt', 3)], [])).toBeNull();
    expect(checkFiles([f('a.txt', 0)], [])).toMatch(/empty/);
    expect(
      checkFiles(
        Array.from({ length: 11 }, (_, i) => f(`${i}.txt`, 1)),
        [],
      ),
    ).toMatch(/At most 10/);
    expect(mimeOf({ name: 'x.docx', type: '' })).toContain('wordprocessingml');
    expect(previewKind({ name: 'x.csv', mime: 'text/csv' })).toBe('csv');
    expect(previewKind({ name: 'x.pdf', mime: 'application/pdf' })).toBe('pdf');
  });

  it('matches and parses slash commands', () => {
    expect(matchCommands('/re', true)?.map((c) => c.name)).toEqual(['rename', 'retry']);
    expect(matchCommands('/re', false)?.map((c) => c.name)).toEqual([]);
    expect(matchCommands('hello', true)).toBeNull();
    expect(parseCommand('/rename  Better title ')).toMatchObject({
      command: { name: 'rename' },
      arg: 'Better title',
    });
    expect(parseCommand('/nope')).toBeNull();
  });
});
