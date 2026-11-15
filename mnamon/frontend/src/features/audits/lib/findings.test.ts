import { describe, expect, it } from 'vitest';
import {
  articleOf,
  gapList,
  judgeCall,
  judgesAgree,
  obligationEntries,
  panelFindings,
  sortFindings,
  textList,
  type SealedFinding,
} from './findings';
import { derivedTraffic, reportModel } from './report';
import type { AuditDetail } from './types';

function sealed(over: Partial<SealedFinding>): SealedFinding {
  return {
    id: 'f1',
    audit_id: 'A',
    system_id: 'SYS-001',
    obligation_id: 'OBL.AIA.10.2.f',
    verdict: 'gap',
    severity: 'critical',
    gap_id: 'G-01',
    metrics_ref: null,
    evidence_refs: [{ path: '/audit/p.parquet', sha256: 'ab'.repeat(32), mlflow_run_id: 'r1' }],
    citations: [{ provision_id: 'AIA.10.2.f', kb_version: 'k1' }],
    kb_version: 'k1',
    reasoning: 'r',
    counter_arguments: ['c'],
    would_change_if: ['w'],
    judges: { rule: 'gap', gemini: { verdict: 'gap' }, iris: { verdict: 'pass', rationale: 'x' } },
    critic: { upheld: true, objection: 'o' },
    data: {},
    prev_hash: null,
    hash: 'h'.repeat(64),
    created_by: 'agent',
    created_at: '2026-11-15T10:00:00Z',
    status: 'current',
    stale: false,
    sealed: true,
    annotations: [],
    status_events: [],
    ...over,
  };
}

const audit = (over: Partial<AuditDetail> = {}): AuditDetail => ({
  id: 'A',
  systemId: 'SYS-001',
  status: 'done',
  stage: 'report',
  createdBy: null,
  data: {},
  createdAt: '2026-11-15T10:00:00Z',
  updatedAt: '2026-11-15T10:00:00Z',
  artifacts: [],
  approvals: [],
  ...over,
});

describe('sealed findings helpers', () => {
  it('derives the article from the obligation id', () => {
    expect(articleOf({ obligation_id: 'OBL.AIA.10.2.f', data: {} })).toBe('Art. 10(2)(f)');
    expect(articleOf({ obligation_id: 'X', data: { article: 'Art. 15' } })).toBe('Art. 15');
    expect(articleOf({ obligation_id: 'X', data: {} })).toBeNull();
  });

  it('reads judge calls in both shapes and flags disagreement', () => {
    expect(judgeCall('gap')?.verdict).toBe('gap');
    expect(judgeCall({ call: 'pass', reason: 'ok' })).toMatchObject({ verdict: 'pass', rationale: 'ok' });
    expect(judgesAgree({ rule: 'gap', gemini: 'gap', iris: 'pass' })).toBe(false);
    expect(judgesAgree({ rule: 'gap', gemini: 'gap' })).toBe(true);
    expect(judgesAgree({ rule: 'gap' })).toBeNull();
  });

  it('normalises text lists', () => {
    expect(textList('a')).toEqual(['a']);
    expect(textList([{ text: 'b' }, 'c'])).toEqual(['b', 'c']);
    expect(textList(null)).toEqual([]);
  });

  it('sorts gaps by severity first and builds the gap list', () => {
    const rows = [
      sealed({ id: 'p', obligation_id: 'OBL.AIA.15', verdict: 'pass', severity: null, gap_id: null }),
      sealed({ id: 'm', obligation_id: 'OBL.AIA.12', severity: 'medium', gap_id: 'G-02' }),
      sealed({ id: 'c' }),
    ];
    expect(sortFindings(rows).map((r) => r.id)).toEqual(['c', 'm', 'p']);
    expect(gapList(rows).map((g) => g.gapId)).toEqual(['G-01', 'G-02']);
  });

  it('falls back to finding artifacts when no sealed rows exist', () => {
    const artifacts = [
      {
        id: 'x',
        auditId: 'A',
        kind: 'finding',
        name: 'F-01',
        version: 1,
        status: 'proposed',
        data: { id: 'F-01', requirement: 'AIA.10', title: 't', verdict: 'indicates_gap' },
        fileRefs: [],
        parentId: null,
        createdBy: 'agent',
        createdAt: '',
        updatedAt: '',
      },
    ];
    const rows = panelFindings([], artifacts, 'A', 'SYS-001');
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ verdict: 'gap', sealed: false, obligation_id: 'AIA.10' });
    expect(panelFindings([sealed({})], artifacts, 'A', 'SYS-001')[0].sealed).toBe(true);
  });

  it('parses obligation map entries', () => {
    const entries = obligationEntries({
      entries: [
        { obligation_id: 'OBL.AIA.10.2.f', applicable: true, reason: 'Annex III 4(a)', in_force_now: true },
        { id: 'OBL.AIA.50.1', applicable: false },
      ],
    });
    expect(entries.map((e) => [e.obligation_id, e.applicable])).toEqual([
      ['OBL.AIA.10.2.f', true],
      ['OBL.AIA.50.1', false],
    ]);
    expect(obligationEntries([{ obligation_id: 'a', applicable: true }])).toHaveLength(1);
    expect(obligationEntries(null)).toEqual([]);
  });
});

describe('report model', () => {
  it('derives traffic lights, gap list and evidence register from sealed findings', () => {
    const rows = [
      sealed({}),
      sealed({ id: 'p', obligation_id: 'OBL.AIA.15.1', verdict: 'pass', gap_id: null, severity: null }),
    ];
    expect(derivedTraffic(rows)?.map((t) => [t.requirement, t.light])).toEqual([
      ['Art. 10', 'red'],
      ['Art. 15', 'green'],
    ]);
    const m = reportModel(audit(), rows);
    expect(m.managementDerived).toBe(true);
    expect(m.gaps).toHaveLength(1);
    expect(m.evidence).toHaveLength(2);
    expect(m.incomplete).toBeNull();
  });

  it('reads the pipeline report and an incomplete report for a failed audit', () => {
    const report = {
      id: 'r',
      auditId: 'A',
      kind: 'report',
      name: 'main',
      version: 1,
      status: 'proposed',
      data: {
        engineer_markdown: '# Eng',
        management: { headline: 'H', traffic_lights: [], decisions_needed: ['d'], next_steps: [] },
        bias_fairness_markdown: '# B&F',
        gap_list: [{ gap_id: 'G-09', obligation_id: 'OBL.X', severity: 'high' }],
      },
      fileRefs: [],
      parentId: null,
      createdBy: 'agent',
      createdAt: '',
      updatedAt: '',
    };
    const m = reportModel(audit({ artifacts: [report] }), []);
    expect(m.engineer?.markdown).toBe('# Eng');
    expect(m.management?.title).toBe('H');
    expect(m.bias).toBe('# B&F');
    expect(m.gaps.map((g) => g.gapId)).toEqual(['G-09']);

    const failed = reportModel(audit({ status: 'failed', stage: 'run_tests', data: { error: 'boom' } }), []);
    expect(failed.incomplete?.reason).toBe('boom');
    expect(failed.incomplete?.notRun[0]).toBeTruthy();
  });
});
