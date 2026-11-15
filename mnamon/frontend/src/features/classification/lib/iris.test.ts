import { describe, expect, it } from 'vitest';
import { toResult } from './classification';
import {
  collapseGroups,
  groupClaims,
  irisFor,
  irisSummaryOf,
  irisSupport,
  irisVerdict,
  toIrisClaims,
} from './iris';
import type { IrisClaim } from './types';

const c = (key: string, agent: boolean, iris: number | null, extra: Partial<IrisClaim> = {}): IrisClaim => {
  const group = key.split(':')[0] as IrisClaim['group'];
  const ref = key.split(':')[1];
  const agrees = iris === null ? null : iris >= 0.5 === agent;
  return {
    key,
    group,
    provision_id: ref?.startsWith('AIA.') ? ref : null,
    statement: `S ${key}`,
    agent,
    iris,
    agrees,
    strong_disagreement: false,
    ...extra,
  };
};

const CLAIMS = [
  c('annex_iii:AIA.ANNEX_III.4.a', true, 0.93),
  c('art5:AIA.5.1.f', false, 0.04),
  c('art6_3:condition', true, 0.71),
  c('art6_3:profiling', false, 0.6),
  c('role', true, 0.95),
  c('assumption:ai_system', true, 0.9),
  c('assumption:no_ranking', true, 0.08, { strong_disagreement: true }),
  c('counter:1', false, null),
];

describe('irisFor', () => {
  it('matches by key, by <group>:<ref> and by provision id, within the group', () => {
    expect(irisFor(CLAIMS, 'AIA.ANNEX_III.4.a', 'annex_iii')?.iris).toBe(0.93);
    expect(irisFor(CLAIMS, 'condition', 'art6_3')?.key).toBe('art6_3:condition');
    expect(irisFor(CLAIMS, 'role', 'role')?.key).toBe('role');
    expect(irisFor(CLAIMS, '1', 'counter')?.key).toBe('counter:1');
    expect(irisFor(CLAIMS, 'AIA.5.1.f', 'annex_iii')).toBeUndefined();
    expect(irisFor(undefined, 'role', 'role')).toBeUndefined();
  });

  it('matches a provision id even when the key differs', () => {
    const odd = [{ ...c('art50:x', false, 0.1), provision_id: 'AIA.50.1' }];
    expect(irisFor(odd, 'AIA.50.1', 'art50')?.key).toBe('art50:x');
  });
});

describe('verdicts', () => {
  it('reads agree / disagree / strong / none and the support for the agent', () => {
    expect(CLAIMS.map(irisVerdict)).toEqual([
      'agree',
      'agree',
      'agree',
      'disagree',
      'agree',
      'agree',
      'strong',
      'none',
    ]);
    expect(irisSupport(CLAIMS[1])).toBeCloseTo(0.96);
    expect(irisSupport(CLAIMS[0])).toBe(0.93);
    expect(irisSupport(CLAIMS[7])).toBeNull();
  });

  it('counts the summary, preferring the sent one', () => {
    expect(irisSummaryOf(CLAIMS, null)).toEqual({ checked: 7, agree: 5, disagree: 2 });
    expect(irisSummaryOf(CLAIMS, { checked: 9, agree: 8, disagree: 1 })).toEqual({
      checked: 9,
      agree: 8,
      disagree: 1,
    });
    expect(irisSummaryOf([], undefined)).toBeNull();
  });
});

describe('groupClaims', () => {
  it('orders groups, puts disagreements first in a group and drops empty groups', () => {
    const g = groupClaims(CLAIMS);
    expect(g.map((x) => x.label)).toEqual([
      'Annex III areas',
      'Art. 5 practices',
      'Art. 6(3) derogation',
      'Role',
      'Assumptions',
      'Counter-arguments',
    ]);
    expect(g[2].claims.map((x) => x.key)).toEqual(['art6_3:profiling', 'art6_3:condition']);
    expect(g[4].claims.map((x) => x.key)).toEqual(['assumption:no_ranking', 'assumption:ai_system']);
  });

  it('collapses to every disagreement plus the first N others', () => {
    const { groups, hidden } = collapseGroups(groupClaims(CLAIMS), 2);
    const keys = groups.flatMap((g) => g.claims.map((x) => x.key));
    expect(keys).toEqual([
      'annex_iii:AIA.ANNEX_III.4.a',
      'art5:AIA.5.1.f',
      'art6_3:profiling',
      'assumption:no_ranking',
    ]);
    expect(hidden).toBe(4);
  });
});

describe('normalising', () => {
  it('drops malformed claims and treats a missing field as empty', () => {
    expect(toIrisClaims([{ key: 'role', statement: 'x', agent: true, iris: 0.5 }, { key: 1 }, 'x'])).toEqual([
      {
        key: 'role',
        group: 'role',
        provision_id: null,
        statement: 'x',
        agent: true,
        iris: 0.5,
        agrees: null,
        strong_disagreement: false,
      },
    ]);
    const r = toResult({});
    expect(r?.iris_claims).toEqual([]);
    expect(r?.iris_summary).toBeNull();
  });
});
