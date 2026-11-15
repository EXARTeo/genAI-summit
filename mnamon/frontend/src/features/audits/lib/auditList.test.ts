import { describe, expect, it } from 'vitest';
import { auditPhase, formatRunTime, phaseCounts, runSeconds, verdictBuckets } from './auditList';

describe('auditList', () => {
  it('buckets old and new verdict names', () => {
    const b = verdictBuckets({
      verdicts: {
        gap: 10,
        indicates_gap: 1,
        pass: 2,
        supports_compliance: 1,
        partial: 3,
        inconclusive: 1,
        not_assessable_by_testing: 18,
      },
    });
    expect(Object.fromEntries(b!.map((x) => [x.id, x.count]))).toEqual({
      gap: 11,
      review: 4,
      pass: 3,
      na: 18,
    });
    expect(verdictBuckets({})).toBeNull();
    expect(verdictBuckets({ verdicts: { gap: 0 } })).toBeNull();
  });

  it('maps statuses to phases and counts them', () => {
    expect(auditPhase({ status: 'completed' })).toBe('done');
    expect(auditPhase({ status: 'open' })).toBe('running');
    const c = phaseCounts([{ status: 'done' }, { status: 'waiting_approval' }, { status: 'failed' }]);
    expect(c).toMatchObject({ all: 3, done: 1, waiting: 1, failed: 1, running: 0 });
  });

  it('prefers summed stage durations, else wall time', () => {
    expect(runSeconds({ createdAt: '2026-11-15T06:46:00Z', data: { stageDurations: { a: 40, b: 2 } } })).toBe(
      42,
    );
    expect(
      runSeconds({
        createdAt: '2026-11-15T06:46:00Z',
        data: { stageDurations: {}, finishedAt: '2026-11-15T06:53:44Z' },
      }),
    ).toBe(464);
    expect(formatRunTime(464)).toBe('7m 44s');
    expect(formatRunTime(null)).toBe('');
  });
});
