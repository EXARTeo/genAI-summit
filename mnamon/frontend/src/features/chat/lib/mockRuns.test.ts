// The mock run simulator end to end: start → stream → pause on approval → approve → answer.
import { describe, expect, it } from 'vitest';
import { mockChat, subscribeMockRun } from './mockRuns';
import { mergeRunUpdate, type LiveRun } from './runState';
import { pendingInterrupts, timelineText } from './timeline';
import type { RunFrame } from './types';

const tick = () => new Promise((r) => setTimeout(r, 5));

async function until(check: () => boolean) {
  for (let i = 0; i < 400 && !check(); i += 1) await tick();
  expect(check()).toBe(true);
}

describe('mock runs', () => {
  it('streams, pauses on a HITL approval and finishes after approve', async () => {
    const started = mockChat.start({
      mode: 'new',
      agentSlug: 'assistant',
      systemId: 'SYS-001',
      message: { sender: 'user', content: 'Why F-001?' },
    });
    expect(started?.summary.systemId).toBe('SYS-001');
    let run: LiveRun | null = null;
    let terminal = false;
    subscribeMockRun(started!.run.id, (frame: RunFrame) => {
      if (frame.type === 'event') {
        const p = frame.payload;
        run = mergeRunUpdate(
          run,
          p.type === 'events'
            ? { type: 'events', run: p.run, events: p.events }
            : { type: p.type, run: p.run },
        );
      } else if (frame.payload) {
        run = mergeRunUpdate(run, { type: frame.type, run: frame.payload.run });
        terminal ||= frame.type === 'terminal';
      }
    });
    await until(() => pendingInterrupts(run?.timeline).length === 1);
    expect(run!.timeline.blocks.some((b) => b.kind === 'subagent')).toBe(true);
    mockChat.resume(started!.run.id, {
      decision: 'approve',
      interruptId: pendingInterrupts(run!.timeline)[0].id,
    });
    await until(() => terminal);
    expect(run!.status).toBe('completed');
    expect(timelineText(run!.timeline)).toContain('F-001 is a gap');
    const stored = mockChat.get(started!.summary.id)!.messages.find((m) => m.id === started!.run.id)!;
    expect(stored.streamingStatus).toBe('completed');
    expect(stored.attachments[0]?.origin).toBe('generated');
  });
});
