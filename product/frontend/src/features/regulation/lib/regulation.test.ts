import { describe, expect, it } from 'vitest';
import { buildMockChanges, buildMockSources, mockDocDiff } from './mocks';
import {
  bindingLabel,
  diffStats,
  effectiveDecision,
  latestVersion,
  openChanges,
  parseUnifiedDiff,
  worstDecision,
} from './regulation';

describe('regulation helpers', () => {
  it('labels binding values', () => {
    expect(bindingLabel(true).label).toBe('Binding');
    expect(bindingLabel(false).label).toBe('Non-binding');
    expect(bindingLabel('internal').tone).toBe('info');
  });

  it('prefers the human override over the change judge', () => {
    expect(effectiveDecision({ decision: 'new_tests_needed', humanDecision: 'reinterpret_existing_evidence' })).toBe(
      'reinterpret_existing_evidence',
    );
    expect(effectiveDecision({ decision: 'rerun_tests', humanDecision: null })).toBe('rerun_tests');
  });

  it('finds the worst decision of a change', () => {
    const [rc7, rc6, rc4] = buildMockChanges();
    expect(worstDecision(rc7)).toBe('rerun_tests');
    expect(worstDecision(rc6)).toBe('reinterpret_existing_evidence');
    expect(worstDecision(rc4)).toBe('no_impact');
    expect(openChanges([rc7, rc6, rc4]).map((c) => c.id)).toEqual(['RC-0007']);
  });

  it('parses unified diffs', () => {
    const lines = parseUnifiedDiff(mockDocDiff('x').unified);
    expect(lines[0].type).toBe('meta');
    expect(lines.some((l) => l.type === 'hunk')).toBe(true);
    expect(diffStats(lines)).toEqual({ added: 7, removed: 2 });
  });

  it('reads the latest version', () => {
    const omnibus = buildMockSources().find((s) => s.id === 'digital-omnibus-ai')!;
    expect(latestVersion(omnibus)).toBe(2);
  });
});
