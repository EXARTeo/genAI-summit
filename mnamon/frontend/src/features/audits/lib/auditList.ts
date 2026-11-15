// Pure helpers for the Audits list: phase, verdict buckets, run time and filters.
import { STAGES, stageIndex } from './pipeline';
import type { Tone } from './styling';
import type { Audit } from './types';

export type AuditPhase = 'running' | 'waiting' | 'done' | 'failed';

export function auditPhase(a: Pick<Audit, 'status'>): AuditPhase {
  if (a.status === 'done' || a.status === 'completed') return 'done';
  if (a.status === 'failed') return 'failed';
  if (a.status === 'waiting_approval') return 'waiting';
  return 'running';
}

export type PhaseFilter = 'all' | AuditPhase;

export const PHASE_FILTERS: { id: PhaseFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'running', label: 'Running' },
  { id: 'waiting', label: 'Waiting' },
  { id: 'done', label: 'Done' },
  { id: 'failed', label: 'Failed' },
];

export function phaseCounts(audits: Pick<Audit, 'status'>[]): Record<PhaseFilter, number> {
  const out: Record<PhaseFilter, number> = { all: audits.length, running: 0, waiting: 0, done: 0, failed: 0 };
  for (const a of audits) out[auditPhase(a)] += 1;
  return out;
}

/** 1-based current step (clamped to the pipeline). */
export function currentStep(a: Pick<Audit, 'stage'>): { n: number; label: string } {
  const i = stageIndex(a.stage);
  const idx = i < 0 ? 0 : i;
  return { n: idx + 1, label: STAGES[idx]?.label ?? a.stage };
}

export interface VerdictBucket {
  id: 'gap' | 'review' | 'pass' | 'na';
  label: string;
  short: string;
  tone: Tone;
  count: number;
}

const BUCKET_OF: Record<string, VerdictBucket['id']> = {
  gap: 'gap',
  indicates_gap: 'gap',
  partial: 'review',
  inconclusive: 'review',
  pass: 'pass',
  supports_compliance: 'pass',
  not_assessable_by_testing: 'na',
  not_applicable: 'na',
};

const BUCKETS: Omit<VerdictBucket, 'count'>[] = [
  { id: 'gap', label: 'Gaps', short: 'gaps', tone: 'danger' },
  { id: 'review', label: 'Partial / inconclusive', short: 'review', tone: 'warning' },
  { id: 'pass', label: 'Pass', short: 'pass', tone: 'success' },
  { id: 'na', label: 'Not assessable by testing', short: 'n/a', tone: 'neutral' },
];

/** Verdict counts grouped into four buckets (accepts old and new verdict names). Null if none. */
export function verdictBuckets(data: Audit['data']): VerdictBucket[] | null {
  const raw = data.verdicts;
  if (!raw || typeof raw !== 'object') return null;
  const counts: Record<VerdictBucket['id'], number> = { gap: 0, review: 0, pass: 0, na: 0 };
  let total = 0;
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof v !== 'number' || v <= 0) continue;
    counts[BUCKET_OF[k] ?? 'na'] += v;
    total += v;
  }
  if (total === 0) return null;
  return BUCKETS.map((b) => ({ ...b, count: counts[b.id] }));
}

/** Run time in seconds: summed agent stage time, else start → finish wall time. */
export function runSeconds(a: Pick<Audit, 'data' | 'createdAt'>): number | null {
  const d = a.data.stageDurations;
  if (d) {
    const sum = Object.values(d).reduce((s, x) => s + (typeof x === 'number' ? x : 0), 0);
    if (sum > 0) return sum;
  }
  const end = typeof a.data.finishedAt === 'string' ? Date.parse(a.data.finishedAt) : NaN;
  const start = Date.parse(a.createdAt);
  if (Number.isNaN(end) || Number.isNaN(start) || end <= start) return null;
  return (end - start) / 1000;
}

/** "7m 44s", "42s", "1h 05m". */
export function formatRunTime(seconds: number | null): string {
  if (seconds == null) return '';
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, '0')}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`;
}

/** "15 Nov, 06:46" (adds the year when it is not this year). */
export function formatRunDate(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const day = d.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    ...(d.getFullYear() !== now.getFullYear() ? { year: 'numeric' } : {}),
  });
  const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  return `${day}, ${time}`;
}

/** The failing step's reason, if the backend recorded one. */
export function failureReason(data: Audit['data']): string | null {
  const f = data.failure as { reason?: unknown } | null | undefined;
  if (f && typeof f.reason === 'string' && f.reason.trim()) return f.reason.trim();
  return typeof data.error === 'string' && data.error.trim() ? data.error.trim() : null;
}
