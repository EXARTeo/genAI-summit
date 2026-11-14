import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { InferenceRunOut } from '../lib/types';

const giveUp: { fn: ((reason: string) => void) | null } = { fn: null };

vi.mock('../lib/transport', () => ({
  subscribeRun: (_id: string, handlers: { onGiveUp?: (reason: string) => void }) => {
    giveUp.fn = handlers.onGiveUp ?? null;
    return () => undefined;
  },
}));

const listRuns = vi.fn<() => Promise<InferenceRunOut[]>>();
vi.mock('../handlers/chat', () => ({ listRuns: () => listRuns() }));

const { seedRun, useRunStore } = await import('./runStore');

const run = (status: string): InferenceRunOut =>
  ({
    id: 'run-1',
    conversationId: 'conv-1',
    assistantMessageId: 'run-1',
    messagePath: [],
    rawEvents: [],
    status,
    startedAt: '2026-11-15T00:00:00Z',
    errorMessage: status === 'failed' ? 'The agents service refused the run (400).' : null,
  }) as unknown as InferenceRunOut;

describe('runStore socket fallback', () => {
  beforeEach(() => {
    useRunStore.setState({ runs: {}, decided: {} });
    listRuns.mockReset();
  });

  it('settles a run over REST when the socket gives up', async () => {
    listRuns.mockResolvedValue([run('failed')]);
    seedRun(run('running'));
    expect(useRunStore.getState().runs['run-1']?.status).toBe('running');
    giveUp.fn?.('Lost the connection to the run');
    await vi.waitFor(() => expect(useRunStore.getState().runs['run-1']?.status).toBe('failed'));
    expect(listRuns).toHaveBeenCalledTimes(1);
  });
});
