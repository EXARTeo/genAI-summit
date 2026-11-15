import { describe, expect, it } from 'vitest';
import { buildMockAudits } from '@/features/audits/lib/mocks';
import {
  DEFAULT_EXCLUDE_REASON,
  EMPTY_DRAFT,
  REASONS,
  defaultScenarioSelection,
  openGates,
  publicDataEdits,
  scenarioEdits,
  toApprovalIn,
  validateDraft,
} from './approvals';

describe('open gates', () => {
  it('lists audits paused at a HITL gate', () => {
    const gates = openGates(buildMockAudits());
    expect(gates).toHaveLength(1);
    expect(gates[0]).toMatchObject({
      auditId: 'aud-sys001-r3',
      gate: 'datasets',
      stageId: 'approve_datasets',
    });
    expect(gates[0].artifactIds.length).toBe(2);
  });

  it('ignores audits that are done or mid-step', () => {
    const audits = buildMockAudits().filter((a) => a.id !== 'aud-sys001-r3');
    expect(openGates(audits)).toEqual([]);
  });
});

describe('decision draft', () => {
  it('has the seven reason categories', () => {
    expect(REASONS.map((r) => r.value)).toEqual([
      'wrong_fact',
      'wrong_interpretation',
      'missing_info',
      'wrong_metric',
      'unrealistic_data',
      'org_policy',
      'other',
    ]);
  });

  it('requires a decision and a reason category', () => {
    expect(validateDraft(EMPTY_DRAFT)).toHaveLength(2);
    expect(validateDraft({ ...EMPTY_DRAFT, decision: 'approved', reasonCategory: 'other' })).toEqual([]);
  });

  it('requires a comment to reject', () => {
    const reject = {
      ...EMPTY_DRAFT,
      decision: 'rejected' as const,
      reasonCategory: 'unrealistic_data' as const,
    };
    expect(validateDraft(reject)).toHaveLength(1);
    expect(validateDraft({ ...reject, comment: 'Ages must be 18–67' })).toEqual([]);
  });

  it('builds the backend payload', () => {
    const body = toApprovalIn('datasets', {
      decision: 'rejected',
      reasonCategory: 'unrealistic_data',
      comment: ' Ages must be 18–67 ',
    });
    expect(body).toEqual({
      gate: 'datasets',
      decision: 'rejected',
      artifactId: null,
      reasonCategory: 'unrealistic_data',
      comment: 'Ages must be 18–67',
      edits: {},
    });
    expect(() => toApprovalIn('datasets', EMPTY_DRAFT)).toThrow();
  });
});

describe('public_data gate', () => {
  const base = buildMockAudits().find((a) => a.id === 'aud-sys001-r3')!;
  it('is open only once find_public_data waits', () => {
    const waiting = { ...base, stage: 'find_public_data', status: 'waiting_approval' };
    expect(openGates([waiting])[0]).toMatchObject({ gate: 'public_data', stageId: 'find_public_data' });
    expect(openGates([{ ...waiting, status: 'running' }])).toEqual([]);
  });

  it('sends the picked dataset as edits.selected', () => {
    const body = toApprovalIn(
      'public_data',
      { decision: 'approved', reasonCategory: 'other', comment: '' },
      'art-1',
      publicDataEdits('uci:597'),
    );
    expect(body.edits).toEqual({ selected: 'uci:597' });
    expect(publicDataEdits(null)).toEqual({});
  });
});

describe('scenarios gate', () => {
  const all = ['SC-01', 'SC-02', 'SC-03', 'SC-04'];

  it('sends no selection when every scenario is approved', () => {
    expect(scenarioEdits(all, all)).toEqual({});
    expect(scenarioEdits(['SC-04', 'SC-01', 'SC-03', 'SC-02'], all)).toEqual({});
  });

  it('sends the kept ids in plan order and a reason for every excluded one', () => {
    const edits = scenarioEdits(['SC-03', 'SC-01'], all, { 'SC-02': '  no such field  ', 'SC-04': ' ' });
    expect(edits).toEqual({
      approved_scenarios: ['SC-01', 'SC-03'],
      excluded: { 'SC-02': 'no such field', 'SC-04': DEFAULT_EXCLUDE_REASON },
    });
    const body = toApprovalIn(
      'scenarios',
      { decision: 'approved', reasonCategory: 'other', comment: '' },
      'a',
      edits,
    );
    expect(body.edits).toBe(edits);
  });

  it('ignores ids that are not in the plan', () => {
    expect(scenarioEdits(['SC-01', 'SC-99'], ['SC-01', 'SC-02'])).toEqual({
      approved_scenarios: ['SC-01'],
      excluded: { 'SC-02': DEFAULT_EXCLUDE_REASON },
    });
  });

  it('starts with everything checked except what the judge found not relevant', () => {
    expect(
      defaultScenarioSelection([
        { id: 'SC-01', review: { verdict: 'relevant' } },
        { id: 'SC-02', review: { verdict: 'not_relevant' } },
        { id: 'SC-03', review: { verdict: 'needs_change' } },
        { id: 'SC-04' },
      ]),
    ).toEqual(['SC-01', 'SC-03', 'SC-04']);
  });
});
