// Agent memory entries (docs/architecture/agent-context.md §4): one YAML file per entry under
// /memory/org/ or /memory/systems/<id>/, lifecycle proposed → active → (promote) → stale/retired.
import type { ReasonCategory } from '@/features/audits/lib/types';

export type MemoryStatus = 'proposed' | 'active' | 'retired' | 'stale';
export type MemoryKind = 'correction' | 'precedent' | 'preference' | 'quirk';

export interface MemoryEvent {
  action: 'create' | 'update' | 'approve' | 'promote' | 'retire' | 'stale' | 'read' | 'reject';
  actor: string;
  at: string;
  reason?: string;
  runId?: string;
  traceId?: string;
  version?: number;
}

export interface MemoryEntry {
  id: string;
  /** "org" or "system:SYS-001". */
  scope: string;
  kind: MemoryKind;
  appliesTo: { step?: string; requirement?: string; sector?: string; field?: string };
  proposed: string;
  humanDecision: string;
  reasonCategory: ReasonCategory;
  rationale: string;
  author: string;
  approvedBy: string | null;
  promotedFrom: string | null;
  status: MemoryStatus;
  kbVersion: string;
  cardVersion?: number;
  sourceTrace?: string;
  supersedes: string | null;
  version: number;
  usageCount: number;
  lastUsedAt?: string;
  createdAt: string;
  history: MemoryEvent[];
}

export interface MemoryFilter {
  scope: 'all' | 'org' | string; // "system:SYS-001"
  status: 'all' | MemoryStatus;
  query: string;
}
