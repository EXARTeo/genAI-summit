import { beforeEach, describe, expect, it, vi } from 'vitest';
import { applyScenarioSelection, mockDecide, mockGet, resetMockStore } from './mockStore';
import { toScenarios } from './adapters';

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
    expect(mockGet('aud-sys001-r3')!).toMatchObject({ status: 'running', stage: 'run_inference' });
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

  it('a partial scenarios approval keeps the approved ones and records the excluded with a reason', () => {
    const plan = {
      scenarios: [
        { id: 'SC-01', metric: 'flip_rate', obligation_id: 'OBL.AIA.10.2.f' },
        { id: 'SC-02', metric: 'selection_rate_ratio' },
        { id: 'SC-03', metric: 'edge_case_failure_rate' },
      ],
    };
    const out = applyScenarioSelection(plan, {
      approved_scenarios: ['SC-02'],
      excluded: { 'SC-01': 'covered by SC-02' },
    });
    const view = toScenarios(out);
    expect(view.scenarios.map((s) => s.id)).toEqual(['SC-02']);
    expect(view.approvedIds).toEqual(['SC-02']);
    expect(view.excluded).toEqual([
      { id: 'SC-01', reason: 'covered by SC-02', obligationId: 'OBL.AIA.10.2.f', metric: 'flip_rate' },
      {
        id: 'SC-03',
        reason: 'excluded by the reviewer',
        obligationId: undefined,
        metric: 'edge_case_failure_rate',
      },
    ]);
    expect(applyScenarioSelection(plan, {})).toBe(plan);
    expect(applyScenarioSelection(plan, { approved_scenarios: [] })).toBe(plan);
  });
});
