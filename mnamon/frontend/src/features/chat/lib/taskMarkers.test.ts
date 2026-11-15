import { describe, expect, it } from 'vitest';
import { taskNoticeText, taskOutcome, taskSettledText, taskUpdateText } from './taskMarkers';

describe('task marker text', () => {
  it('names the sub-agent and its outcome', () => {
    expect(taskSettledText('general-purpose', 'success')).toBe('General Purpose finished');
    expect(taskSettledText('evidence-analyst', 'error')).toBe('Evidence Analyst failed');
    expect(taskSettledText('x', 'cancelled')).toBe('X was stopped');
  });

  it('adds the duration to a notice row', () => {
    expect(
      taskNoticeText({ task_id: 't', name: 'general-purpose', status: 'success', duration_ms: 22_000 }),
    ).toBe('General Purpose finished · 22s');
    expect(taskNoticeText({ task_id: 't', name: 'general-purpose', status: 'success' })).toBe(
      'General Purpose finished',
    );
  });

  it('reads an update and maps statuses', () => {
    expect(taskUpdateText('general-purpose')).toBe('Sent an update to General Purpose');
    expect(taskOutcome('completed')).toBe('success');
    expect(taskOutcome('running')).toBe('running');
  });
});
