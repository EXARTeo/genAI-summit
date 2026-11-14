// Pure regulation-view logic: binding labels, judge decision styling, diff parsing.
import type { Tone } from '@/features/audits/lib/styling';
import type { Binding, JudgeDecision, RegChange, RegSource } from './types';

export function bindingLabel(b: Binding): { label: string; tone: Tone } {
  if (b === true) return { label: 'Binding', tone: 'danger' };
  if (b === 'internal') return { label: 'Internal policy', tone: 'info' };
  return { label: 'Non-binding', tone: 'neutral' };
}

export const JUDGE: Record<JudgeDecision, { label: string; tone: Tone; rank: number }> = {
  no_impact: { label: 'No impact', tone: 'success', rank: 0 },
  reinterpret_existing_evidence: { label: 'Reinterpret evidence', tone: 'info', rank: 1 },
  rerun_tests: { label: 'Re-run tests', tone: 'warning', rank: 2 },
  new_tests_needed: { label: 'New tests needed', tone: 'danger', rank: 3 },
};

/** The decision that counts: the human override if any, else the judge's. */
export function effectiveDecision(a: { decision: JudgeDecision; humanDecision?: JudgeDecision | null }): JudgeDecision {
  return a.humanDecision ?? a.decision;
}

/** Highest-impact decision across the affected systems of a change. */
export function worstDecision(change: Pick<RegChange, 'affected'>): JudgeDecision {
  return change.affected.reduce<JudgeDecision>(
    (w, a) => (JUDGE[effectiveDecision(a)].rank > JUDGE[w].rank ? effectiveDecision(a) : w),
    'no_impact',
  );
}

export type DiffLine = { type: 'add' | 'del' | 'ctx' | 'hunk' | 'meta'; text: string };

/** Parse a unified diff into typed lines for rendering. */
export function parseUnifiedDiff(diff: string): DiffLine[] {
  return diff
    .split(/\r?\n/)
    .filter((l, i, all) => !(l === '' && i === all.length - 1))
    .map((text) => {
      if (text.startsWith('+++') || text.startsWith('---')) return { type: 'meta' as const, text };
      if (text.startsWith('@@')) return { type: 'hunk' as const, text };
      if (text.startsWith('+')) return { type: 'add' as const, text: text.slice(1) };
      if (text.startsWith('-')) return { type: 'del' as const, text: text.slice(1) };
      return { type: 'ctx' as const, text: text.startsWith(' ') ? text.slice(1) : text };
    });
}

export function diffStats(lines: DiffLine[]): { added: number; removed: number } {
  return {
    added: lines.filter((l) => l.type === 'add').length,
    removed: lines.filter((l) => l.type === 'del').length,
  };
}

export function latestVersion(s: Pick<RegSource, 'versions'>): number {
  return s.versions.reduce((m, v) => Math.max(m, v.version), 0);
}

export function openChanges(changes: RegChange[]): RegChange[] {
  return changes.filter((c) => c.status === 'proposed');
}
