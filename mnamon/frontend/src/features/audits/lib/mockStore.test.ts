import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mockDecide, mockGet, resetMockStore } from './mockStore';

describe('mock audit store', () => {
  beforeEach(() => {
    resetMockStore();
    vi.useRealTimers();
  });

  it('reveals only artifacts of finished stages at a gate', () => {
    const a = mockGet('aud-sys001-r3')!;
    expect(a.status).toBe('waiting_approval');
    expect(a.artifacts.map((x) => x.kind)).not.toContain('finding');
    expect(a.artifacts.map((x) => x.kind)).toContain('dataset_analysis');
  });

  it('approving the dataset gate starts the run and it finishes over time', () => {
    vi.useFakeTimers();
    const res = mockDecide('aud-sys001-r3', {
      gate: 'datasets',
      decision: 'approved',
      reasonCategory: 'other',
    })!;
    expect(res.approval.decision).toBe('approved');
    expect(mockGet('aud-sys001-r3')!).toMatchObject({ status: 'running', stage: 'run_tests' });
    vi.advanceTimersByTime(60_000);
    const done = mockGet('aud-sys001-r3')!;
    expect(done.status).toBe('done');
    expect(done.artifacts.filter((x) => x.kind === 'report')).toHaveLength(2);
  });

  it('a rejection with a reason sends the agent back and stops again at the gate', () => {
    vi.useFakeTimers();
    const res = mockDecide('aud-sys001-r3', {
      gate: 'datasets',
      decision: 'rejected',
      reasonCategory: 'unrealistic_data',
      comment: 'Ages 18–67',
    })!;
    expect(res.approval.decision).toBe('rejected');
    vi.advanceTimersByTime(60_000);
    expect(mockGet('aud-sys001-r3')!).toMatchObject({
      status: 'waiting_approval',
      stage: 'approve_datasets',
    });
  });
});
