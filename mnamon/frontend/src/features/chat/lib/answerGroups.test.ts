import { describe, expect, it } from 'vitest';
import { answerGroupText, groupAnswers } from './answerGroups';
import type { MessageOut } from './types';

const msg = (id: string, sender: 'user' | 'ai', extra: Partial<MessageOut> = {}): MessageOut =>
  ({
    id,
    sender,
    content: `${id} text`,
    attachments: [],
    created_at: '2026-11-15T00:00:00Z',
    updated_at: '2026-11-15T00:00:00Z',
    ...extra,
  }) as MessageOut;

describe('groupAnswers', () => {
  const path = [
    msg('u1', 'user'),
    msg('a1', 'ai'),
    msg('n1', 'user', { kind: 'task_notification' }),
    msg('a2', 'ai'),
    msg('n2', 'user', { kind: 'task_notification' }),
    msg('a3', 'ai'),
    msg('u2', 'user'),
    msg('a4', 'ai'),
  ];

  it('stacks the answer and its wake-up replies into one group', () => {
    const places = groupAnswers(path);
    const first = places.get('a1')!;
    expect(first.group.members.map((m) => m.id)).toEqual(['a1', 'a2', 'a3']);
    expect(first.isTail).toBe(false);
    expect(places.get('a3')!.isTail).toBe(true);
    expect(places.get('a2')!.group.head.id).toBe('a1');
  });

  it('starts a new group at a real user message', () => {
    const places = groupAnswers(path);
    expect(places.get('a4')!.group.members.map((m) => m.id)).toEqual(['a4']);
    expect(places.get('a4')!.isTail).toBe(true);
  });

  it('copies every member in order', () => {
    const group = groupAnswers(path).get('a1')!.group;
    expect(answerGroupText(group)).toBe('a1 text\n\na2 text\n\na3 text');
  });
});
