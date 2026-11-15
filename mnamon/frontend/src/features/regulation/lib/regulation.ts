// Pure regulation-view logic: binding labels, judge decision styling, diff parsing.
import type { Tone } from '@/features/audits/lib/styling';
import type { Binding, ChangeFile, JudgeDecision, RegChange, RegSource, ReleaseList } from './types';

export function bindingLabel(b: Binding): { label: string; tone: Tone } {
  if (b === true) return { label: 'Binding', tone: 'info' };
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
export function effectiveDecision(a: {
  decision: JudgeDecision;
  humanDecision?: JudgeDecision | null;
}): JudgeDecision {
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

/** Provisions with a text in reg-memory's provision store (interpretations `INT.*` have none there). */
const PROVISION_ID = /^(AIA|OMNIBUS)\./;

/**
 * The "files changed" of a change: each provision is one file (diffed across kb versions); the
 * interpretation nodes of a guideline collapse into one diff of the source document itself.
 */
export function changeFiles(
  c: Pick<RegChange, 'provisions' | 'sourceId' | 'fromVersion' | 'toVersion'>,
): ChangeFile[] {
  const files: ChangeFile[] = [];
  const opaque: string[] = [];
  for (const id of c.provisions) {
    if (PROVISION_ID.test(id)) files.push({ kind: 'provision', key: id, id });
    else opaque.push(id);
  }
  if (opaque.length > 0) {
    if (c.toVersion > c.fromVersion) {
      files.unshift({
        kind: 'document',
        key: `doc:${c.sourceId}`,
        docId: c.sourceId,
        from: c.fromVersion,
        to: c.toVersion,
      });
    } else for (const id of opaque) files.push({ kind: 'opaque', key: id, id });
  }
  return files;
}

/** The kb version a candidate was built on (its release's parent). */
export function parentKb(releases: ReleaseList | undefined, kb: string): string | null {
  return releases?.items.find((r) => r.kb_version === kb)?.parent ?? null;
}

/** "AIA.10.2.f" → "Art. 10(2)(f)", "AIA.ANNEX_III.4" → "Annex III 4"; unknown ids unchanged. */
export function provisionLabel(id: string): string {
  const parts = id.split('.');
  const inst = parts.shift();
  if (!inst || parts.length === 0) return id;
  const prefix = inst === 'OMNIBUS' ? 'Omnibus ' : '';
  if (parts[0] === 'REC') return `${prefix}Recital ${parts[1] ?? ''}`.trim();
  const annex = /^ANNEX_(.+)$/.exec(parts[0]);
  if (annex) return `${prefix}Annex ${annex[1]}${parts.length > 1 ? ` ${parts.slice(1).join('.')}` : ''}`;
  return `${prefix}Art. ${parts[0]}${parts
    .slice(1)
    .map((p) => `(${p})`)
    .join('')}`;
}

/** "AIA.10.2.f" → "AIA.10", "AIA.REC.5" → "AIA.REC.5": the top-level provision the reader opens on. */
export function topProvisionId(id: string): string {
  const parts = id.split('.');
  return parts[1] === 'REC' ? parts.slice(0, 3).join('.') : parts.slice(0, 2).join('.');
}

/** A bare source for the reader when the catalog cannot be loaded. */
export function fallbackSource(id: string): RegSource {
  return {
    id,
    title: id,
    kind: 'other',
    binding: false,
    status: 'final',
    publisher: 'catalog unavailable',
    tags: [],
    documents: 0,
    versions: [],
  };
}
