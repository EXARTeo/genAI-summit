import { describe, expect, it } from 'vitest';
import {
  byObligation,
  eventStatus,
  filterItems,
  findingRegisterStatus,
  sortItems,
  stateKey,
  summaryLine,
  toRegister,
} from './register';
import type { RegisterEvent, RegisterItem } from './types';

const ev = (kind: string, to: string, audit: string | null = 'A1'): RegisterEvent => ({
  at: '2026-11-15T09:00:00Z',
  audit_id: audit,
  actor: 'audit:A1',
  kind,
  from: null,
  to,
  verdict: 'gap',
  note: null,
});

function item(over: Partial<RegisterItem>): RegisterItem {
  return toRegister({
    system_id: 'SYS-001',
    items: [{ obligation_id: 'OBL.AIA.10.2.f.bias', state: 'open', verdict: 'gap', ...over }],
  }).items[0];
}

describe('toRegister', () => {
  it('fails open on missing and wrong fields', () => {
    const reg = toRegister({ items: [{ obligation_id: 'X', history: 'nope', last_evidence: [1, 'a'] }] });
    expect(reg.summary.total).toBe(0);
    expect(reg.items[0].history).toEqual([]);
    expect(reg.items[0].last_evidence).toEqual(['a']);
    expect(reg.items[0].state).toBe('open');
    expect(toRegister(null).items).toEqual([]);
  });
});

describe('register status', () => {
  it('maps audit events to the marker', () => {
    expect(eventStatus(ev('opened', 'open'))).toBe('new');
    expect(eventStatus(ev('still_open', 'open'))).toBe('still_open');
    expect(eventStatus(ev('still_open', 'closed'))).toBe('accepted_risk');
    expect(eventStatus(ev('resolved', 'resolved'))).toBe('resolved');
    expect(eventStatus(ev('reopened', 'open'))).toBe('regressed');
    expect(eventStatus(ev('reopened', 'open', null))).toBeNull();
  });

  it('reads the register event of the finding audit, else the stamped status', () => {
    const map = byObligation([
      item({ history: [ev('opened', 'open', 'A1'), ev('resolved', 'resolved', 'A2')] }),
    ]);
    const f = (audit: string, data = {}) => ({ audit_id: audit, obligation_id: 'OBL.AIA.10.2.f.bias', data });
    expect(findingRegisterStatus(f('A1'), map)).toBe('new');
    expect(findingRegisterStatus(f('A2'), map)).toBe('resolved');
    expect(findingRegisterStatus(f('A3', { register_status: 'still_open' }), map)).toBe('still_open');
    expect(findingRegisterStatus(f('A3', { register_status: 'bogus' }), map)).toBeNull();
  });
});

describe('view helpers', () => {
  const rows = [
    item({ obligation_id: 'OBL.AIA.15.1', state: 'resolved', verdict: 'pass' }),
    item({ obligation_id: 'OBL.AIA.9.2', verdict: 'inconclusive' }),
    item({ obligation_id: 'OBL.AIA.10.2.f', severity: 'critical', close_reason: null }),
    item({ obligation_id: 'OBL.AIA.13', state: 'closed', close_reason: 'Wiki covers it' }),
  ];

  it('splits needs review from open and sorts open first', () => {
    expect(stateKey(rows[1])).toBe('needs_review');
    expect(sortItems(rows).map((r) => r.obligation_id)).toEqual([
      'OBL.AIA.10.2.f',
      'OBL.AIA.9.2',
      'OBL.AIA.13',
      'OBL.AIA.15.1',
    ]);
  });

  it('filters by state, chapter and text (close reasons too)', () => {
    const base = { query: '', states: [], verdicts: [], severities: [], chapters: [] };
    expect(filterItems(rows, { ...base, states: ['closed'] })).toHaveLength(1);
    expect(filterItems(rows, { ...base, query: 'wiki' })[0].obligation_id).toBe('OBL.AIA.13');
    expect(filterItems(rows, { ...base, severities: ['critical'] })).toHaveLength(1);
  });

  it('writes the overview line', () => {
    expect(
      summaryLine({
        total: 12,
        by_state: {},
        by_verdict: {},
        open_gaps: 7,
        needs_review: 0,
        accepted_risks: 2,
        resolved: 1,
        monitoring: 2,
      }),
    ).toBe('7 open gaps · 2 accepted risks · 1 resolved');
  });
});
