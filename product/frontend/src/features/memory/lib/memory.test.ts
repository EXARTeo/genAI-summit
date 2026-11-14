import { describe, expect, it } from 'vitest';
import { allowedActions, filterMemory, nextMemoryId, scopeLabel, scopesOf } from './memory';
import { buildMockMemory } from './mocks';

const ledger = buildMockMemory();

describe('memory ledger', () => {
  it('filters by scope, status and text', () => {
    expect(filterMemory(ledger, { scope: 'org', status: 'all', query: '' }).every((e) => e.scope === 'org')).toBe(true);
    expect(filterMemory(ledger, { scope: 'all', status: 'stale', query: '' }).map((e) => e.id)).toEqual(['MEM-0021']);
    expect(filterMemory(ledger, { scope: 'all', status: 'all', query: 'equal opportunity' }).map((e) => e.id)).toEqual([
      'MEM-0042',
      'MEM-0039',
    ]);
  });

  it('labels scopes and lists them with org first', () => {
    expect(scopeLabel('org')).toBe('Org-wide');
    expect(scopeLabel('system:SYS-001')).toBe('SYS-001');
    expect(scopesOf(ledger)).toEqual(['org', 'system:SYS-001', 'system:SYS-002']);
  });

  it('allows lifecycle actions per status and scope', () => {
    expect(allowedActions({ status: 'proposed', scope: 'system:SYS-001' })).toEqual(['approve', 'retire']);
    expect(allowedActions({ status: 'active', scope: 'system:SYS-001' })).toEqual(['promote', 'retire']);
    expect(allowedActions({ status: 'active', scope: 'system:SYS-001' }, true)).toEqual(['retire']);
    expect(allowedActions({ status: 'active', scope: 'org' })).toEqual(['retire']);
    expect(allowedActions({ status: 'stale', scope: 'org' })).toEqual(['reactivate', 'retire']);
    expect(allowedActions({ status: 'retired', scope: 'org' })).toEqual([]);
  });

  it('allocates the next id', () => {
    expect(nextMemoryId(ledger)).toBe('MEM-0067');
    expect(nextMemoryId([])).toBe('MEM-0001');
  });
});
