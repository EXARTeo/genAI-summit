import { describe, expect, it } from 'vitest';
import {
  attention,
  citationFlags,
  formatElapsed,
  inForce,
  previewEntries,
  previousFor,
  provisionLabel,
  routeLabel,
  runPhase,
  staleReason,
  toClassification,
  toClassifications,
} from './classification';

const row = (id: string, status: string, at: string, extra: Record<string, unknown> = {}) => ({
  id,
  system_id: 'SYS-004',
  status,
  created_at: at,
  events: [],
  ...extra,
});

describe('toClassification', () => {
  it('reads snake_case and camelCase rows and fills the result lists', () => {
    const a = toClassification(
      row('C1', 'proposed', '2026-11-15T10:00:00Z', { kb_version: 'k1', result: {} }),
    );
    const b = toClassification({
      id: 'C2',
      systemId: 'S',
      kbVersion: 'k2',
      createdAt: 'x',
      previousId: 'C1',
    });
    expect(a.kbVersion).toBe('k1');
    expect(a.result?.citations).toEqual([]);
    expect(a.result?.needs_human).toBe(false);
    expect(b).toMatchObject({ systemId: 'S', kbVersion: 'k2', previousId: 'C1', result: null });
  });

  it('sorts runs newest first (also from an {items} envelope)', () => {
    const list = toClassifications({
      items: [row('old', 'approved', '2026-11-14T10:00:00Z'), row('new', 'proposed', '2026-11-15T10:00:00Z')],
    });
    expect(list.map((c) => c.id)).toEqual(['new', 'old']);
  });
});

describe('run selection', () => {
  const list = (...rows: ReturnType<typeof row>[]) => toClassifications(rows);

  it('the class in force is the newest approved or stale run', () => {
    const l = list(
      row('a', 'superseded', '2026-11-13T00:00:00Z'),
      row('b', 'stale', '2026-11-14T00:00:00Z'),
      row('c', 'rejected', '2026-11-15T00:00:00Z'),
    );
    expect(inForce(l)?.id).toBe('b');
    expect(attention(l)).toBe('stale');
    expect(previousFor(l)).toBe('c');
  });

  it('a waiting proposal wins the header dot', () => {
    expect(attention(list(row('p', 'proposed', '2026-11-15T00:00:00Z')))).toBe('proposed');
    expect(attention(list(row('a', 'approved', '2026-11-15T00:00:00Z')))).toBeNull();
    expect(previousFor(list(row('a', 'approved', '2026-11-15T00:00:00Z')))).toBeUndefined();
  });
});

describe('labels', () => {
  it('turns provision ids into article labels', () => {
    expect(provisionLabel('AIA.ANNEX_III.4.a')).toBe('Annex III 4(a)');
    expect(provisionLabel('AIA.6.3')).toBe('Art. 6(3)');
    expect(provisionLabel('AIA.5.1.f')).toBe('Art. 5(1)(f)');
    expect(provisionLabel('AIA.4a.1')).toBe('Art. 4a(1)');
    expect(provisionLabel('OMNIBUS.1.12')).toBe('Omnibus Art. 1(12)');
    expect(provisionLabel('INT.demo')).toBe('INT.demo');
  });

  it('names the route, with the 6(3) condition', () => {
    expect(routeLabel('art6_3_exempt', 'a')).toBe('Not high risk: Art. 6(3)(a) derogation');
    expect(routeLabel('art6_2_annex_iii')).toMatch(/Annex III/);
  });

  it('marks guidance non-binding and drafts as drafts', () => {
    expect(citationFlags({ id: 'AIA.6.3', binding: true, status: 'final' })).toEqual({
      binding: true,
      draft: false,
    });
    expect(citationFlags({ id: 'INT.g', binding: true, status: 'draft' })).toEqual({
      binding: false,
      draft: true,
    });
  });

  it('explains why a run went stale', () => {
    const c = toClassification(
      row('s', 'stale', 'x', {
        events: [{ action: 'stale', data: { change_id: 'RC-1', provisions: ['AIA.6.3'] }, at: 'y' }],
      }),
    );
    expect(staleReason(c)).toBe('RC-1 changed AIA.6.3');
    expect(staleReason(toClassification(row('a', 'approved', 'x')))).toBeNull();
  });
});

describe('progress', () => {
  it('estimates the phase and formats the clock', () => {
    expect([runPhase(1_000), runPhase(10_000), runPhase(50_000)]).toEqual([0, 1, 2]);
    expect(formatElapsed(65_000)).toBe('1:05');
  });
});

describe('previewEntries', () => {
  it('labels catalogue rows and lists applicable ones first', () => {
    const e = previewEntries([
      { id: 'OBL.AIA.9.rm', article: 'AIA.9', summary: 'Risk', applicable: false },
      {
        id: 'OBL.AIA.6.4.x',
        article: 'AIA.6.4',
        summary: 'Doc',
        applicable: true,
        in_force_date: '2027-12-02',
      },
    ]);
    expect(e.map((x) => [x.label, x.applicable])).toEqual([
      ['Art. 6(4)', true],
      ['Art. 9', false],
    ]);
  });
});
