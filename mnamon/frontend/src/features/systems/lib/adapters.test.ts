import { describe, expect, it } from 'vitest';
import { toSystem, toSystems, withLastAudits } from './adapters';
import real from './fixtures/systems.json';
import type { System } from './types';

// GET /api/v1/systems (live, first two systems): the card sits under data.card.
describe('system adapter', () => {
  it('flattens data.card so the UI reads risk_class and friends', () => {
    const [s1] = toSystems(real as unknown as System[]);
    expect(s1.data.risk_class).toBe('high_risk');
    expect(s1.data.annex_basis).toBe('Annex III 4(a)');
    expect(s1.data.intended_purpose).toMatch(/Rank applicants/);
    expect(s1.data.source).toBe('seed');
    expect(s1.data.card).toBeUndefined();
  });

  it('passes flat (mock) data through and survives junk', () => {
    const flat = {
      id: 'X',
      name: 'X',
      status: 'active',
      data: { risk_class: 'minimal_risk' },
    } as unknown as System;
    expect(toSystem(flat).data.risk_class).toBe('minimal_risk');
    expect(toSystem({ id: 'Y' } as unknown as System).data).toEqual({});
    expect(toSystems(null as unknown as System[])).toEqual([]);
  });
});

describe('withLastAudits', () => {
  it('takes the newest audit per system and maps waiting_approval', () => {
    const systems = toSystems(real as unknown as System[]);
    const out = withLastAudits(systems, [
      { id: 'a1', systemId: 'SYS-001', status: 'done', updatedAt: '2026-11-14T10:00:00Z', data: {} },
      {
        id: 'a2',
        systemId: 'SYS-001',
        status: 'waiting_approval',
        updatedAt: '2026-11-14T22:00:00Z',
        data: { verdicts: { indicates_gap: 2 } },
      },
    ]);
    expect(out[0].data.last_audit).toMatchObject({
      id: 'a2',
      status: 'awaiting_approval',
      findings: { gaps: 2 },
    });
    expect(out[1].data.last_audit).toBeUndefined();
  });
});
