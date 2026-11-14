import { describe, expect, it } from 'vitest';
import { buildMockAudits } from '@/features/audits/lib/mocks';
import { EMPTY_DRAFT, REASONS, openGates, publicDataEdits, toApprovalIn, validateDraft } from './approvals';

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
