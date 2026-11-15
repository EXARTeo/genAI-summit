import { describe, expect, it } from 'vitest';
import { foldTaskEvents, transcriptTurns } from './taskTranscript';
import type { RawEvent } from './types';

const text = (id: string, seq: number, delta: string): RawEvent[] => [
  { type: 'TEXT_MESSAGE_START', messageId: id, role: 'assistant', seq },
  { type: 'TEXT_MESSAGE_CONTENT', messageId: id, delta, seq: seq + 1 },
  { type: 'TEXT_MESSAGE_END', messageId: id, seq: seq + 2 },
];

describe('task transcript', () => {
  it('splits the runs of a task at each follow-up, even though seq restarts', () => {
    const events: RawEvent[] = [
      ...text('t', 1, 'First answer.'),
      { type: 'CUSTOM', name: 'TASK_INPUT', value: { text: 'Now check Article 14 too.' } },
      ...text('t', 1, 'Second answer.'),
    ];
    const timeline = foldTaskEvents(events, 'success');
    const turns = transcriptTurns(timeline, 'Describe SYS-001');
    expect(turns.map((t) => t.instruction)).toEqual(['Describe SYS-001', 'Now check Article 14 too.']);
    expect(turns[1].followUp).toBe(true);
    const words = turns.map((t) => t.blocks.map((b) => (b.kind === 'content' ? b.text : '')).join(''));
    expect(words).toEqual(['First answer.', 'Second answer.']);
    expect(timeline.terminal).toBe(true);
  });
});
