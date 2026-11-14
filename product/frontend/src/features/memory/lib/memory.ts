// Pure memory-ledger logic: filtering, scope labels, allowed lifecycle actions.
import type { Tone } from '@/features/audits/lib/styling';
import type { MemoryEntry, MemoryFilter, MemoryStatus } from './types';

export const STATUS_TONE: Record<MemoryStatus, Tone> = {
  proposed: 'info',
  active: 'success',
  stale: 'warning',
  retired: 'neutral',
};

export function scopeLabel(scope: string): string {
  if (scope === 'org') return 'Org-wide';
  return scope.startsWith('system:') ? scope.slice('system:'.length) : scope;
}

export function isOrg(entry: Pick<MemoryEntry, 'scope'>): boolean {
  return entry.scope === 'org';
}

export function filterMemory(entries: MemoryEntry[], f: MemoryFilter): MemoryEntry[] {
  const q = f.query.trim().toLowerCase();
  return entries
    .filter((e) => f.scope === 'all' || e.scope === f.scope)
    .filter((e) => f.status === 'all' || e.status === f.status)
    .filter(
      (e) =>
        !q ||
        [
          e.id,
          e.proposed,
          e.humanDecision,
          e.rationale,
          e.reasonCategory,
          e.appliesTo.requirement ?? '',
          e.appliesTo.step ?? '',
        ]
          .join(' ')
          .toLowerCase()
          .includes(q),
    )
    .sort((a, b) => b.usageCount - a.usageCount || a.id.localeCompare(b.id));
}

export type MemoryAction = 'approve' | 'promote' | 'retire' | 'reactivate';

/**
 * Lifecycle actions a human may take. Agents never call these; they only write proposals.
 * - proposed → approve (activates in its scope) or retire (reject)
 * - active system entry → promote to org (needs the AI Officer) or retire
 * - active org entry → retire
 * - stale → reactivate after re-review, or retire
 */
export function allowedActions(
  e: Pick<MemoryEntry, 'status' | 'scope'>,
  promotedAlready = false,
): MemoryAction[] {
  switch (e.status) {
    case 'proposed':
      return ['approve', 'retire'];
    case 'active':
      return isOrg(e) || promotedAlready ? ['retire'] : ['promote', 'retire'];
    case 'stale':
      return ['reactivate', 'retire'];
    default:
      return [];
  }
}

export function scopesOf(entries: MemoryEntry[]): string[] {
  const systems = Array.from(new Set(entries.map((e) => e.scope).filter((s) => s !== 'org'))).sort();
  return ['org', ...systems];
}

/** Next MEM id after the highest one in the ledger. */
export function nextMemoryId(entries: Pick<MemoryEntry, 'id'>[]): string {
  const max = entries.reduce((m, e) => Math.max(m, Number(e.id.replace(/\D/g, '')) || 0), 0);
  return `MEM-${String(max + 1).padStart(4, '0')}`;
}
