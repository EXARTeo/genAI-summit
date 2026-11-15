// Pure helpers for the findings register: the Zod-validated boundary (fail-open: a bad field
// becomes its default, never a crash), labels and tones, summary, facets and filtering.
import { z } from 'zod';
import { articleLabel, chapterOf, severityMeta, type SealedFinding } from '@/features/audits/lib/findings';
import type { Tone } from '@/features/audits/lib/styling';
import type { Register, RegisterEvent, RegisterItem, RegisterStatus, RegisterSummary } from './types';

const str = z.preprocess((v) => (typeof v === 'string' ? v : undefined), z.string().optional());
const nstr = z.preprocess((v) => (typeof v === 'string' && v ? v : null), z.string().nullable());
const num = z.preprocess((v) => (typeof v === 'number' ? v : 0), z.number());
const counts = z.preprocess(
  (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : {}),
  z.record(z.number()),
);

const eventSchema = z
  .object({
    at: str.transform((v) => v ?? ''),
    audit_id: nstr,
    finding_id: nstr.optional(),
    actor: str.transform((v) => v ?? ''),
    kind: str.transform((v) => v ?? 'unknown'),
    from: nstr,
    to: nstr,
    verdict: nstr,
    previous_verdict: nstr.optional(),
    note: nstr,
  })
  .passthrough();

const itemSchema = z.object({
  id: str.transform((v) => v ?? ''),
  system_id: str.transform((v) => v ?? ''),
  obligation_id: str.transform((v) => v ?? '?'),
  state: str.transform((v) => v ?? 'open'),
  verdict: str.transform((v) => v ?? 'inconclusive'),
  severity: nstr,
  article: nstr,
  title: nstr,
  gap_id: nstr,
  first_seen_audit_id: str.transform((v) => v ?? ''),
  last_seen_audit_id: str.transform((v) => v ?? ''),
  last_finding_id: nstr,
  opened_at: nstr,
  closed_by: nstr,
  close_reason: nstr,
  closed_at: nstr,
  created_at: str.transform((v) => v ?? ''),
  updated_at: str.transform((v) => v ?? ''),
  last_status: nstr,
  last_reasoning: nstr,
  last_evidence: z.preprocess(
    (v) => (Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []),
    z.array(z.string()),
  ),
  history: z.preprocess(
    (v) => (Array.isArray(v) ? v.filter((x) => x && typeof x === 'object') : []),
    z.array(eventSchema),
  ),
});

const summarySchema = z.object({
  total: num,
  by_state: counts,
  by_verdict: counts,
  open_gaps: num,
  needs_review: num,
  accepted_risks: num,
  resolved: num,
  monitoring: num,
});

const registerSchema = z.object({
  system_id: str.transform((v) => v ?? ''),
  summary: z.preprocess((v) => (v && typeof v === 'object' ? v : {}), summarySchema),
  items: z.preprocess(
    (v) => (Array.isArray(v) ? v.filter((x) => x && typeof x === 'object') : []),
    z.array(itemSchema),
  ),
});

export function toRegister(raw: unknown): Register {
  return registerSchema.parse(raw ?? {}) as Register;
}

export function toRegisterItem(raw: unknown): RegisterItem {
  return itemSchema.parse(raw ?? {}) as RegisterItem;
}

// ---- labels ------------------------------------------------------------------------------

export const STATE_META: Record<string, { label: string; tone: Tone; description: string }> = {
  open: {
    label: 'Open',
    tone: 'danger',
    description: 'A gap found by an audit; stays open until fixed or closed.',
  },
  closed: {
    label: 'Accepted risk',
    tone: 'info',
    description: 'Closed by a person with a reason; reopens only on a worse verdict.',
  },
  resolved: { label: 'Resolved', tone: 'success', description: 'A later audit found it passing.' },
  monitoring: {
    label: 'Monitoring',
    tone: 'neutral',
    description: 'No gap so far; every audit checks it again.',
  },
};

export function stateMeta(item: Pick<RegisterItem, 'state' | 'verdict'>) {
  if (item.state === 'open' && item.verdict === 'inconclusive') {
    return {
      label: 'Needs review',
      tone: 'warning' as Tone,
      description: 'Inconclusive: a person must look.',
    };
  }
  return STATE_META[item.state] ?? { label: item.state, tone: 'neutral' as Tone, description: '' };
}

export const STATUS_META: Record<RegisterStatus, { label: string; tone: Tone; description: string }> = {
  new: { label: 'New', tone: 'info', description: 'First time an audit judged this obligation.' },
  still_open: { label: 'Still open', tone: 'neutral', description: 'An earlier audit found this gap too.' },
  resolved: { label: 'Fixed', tone: 'success', description: 'Open before; this audit found it passing.' },
  regressed: { label: 'Regressed', tone: 'danger', description: 'Was fixed or accepted; worse again now.' },
  accepted_risk: {
    label: 'Accepted risk',
    tone: 'neutral',
    description: 'Closed by a person with a reason; the verdict did not get worse.',
  },
  unchanged: { label: 'No change', tone: 'neutral', description: 'Same as before: no gap.' },
};

export const REGISTER_STATUSES = Object.keys(STATUS_META) as RegisterStatus[];

export function statusMeta(s: string | null | undefined) {
  return s ? (STATUS_META[s as RegisterStatus] ?? null) : null;
}

const KIND_LABEL: Record<string, string> = {
  opened: 'Opened',
  first_seen: 'First checked',
  still_open: 'Still open',
  verdict_changed: 'Verdict changed',
  resolved: 'Resolved',
  regressed: 'Regressed',
  closed: 'Closed',
  reopened: 'Reopened',
  checked: 'Checked again',
};

export function eventLabel(e: RegisterEvent): string {
  if (e.kind === 'still_open' && e.to === 'closed') return 'Found again (accepted risk)';
  return KIND_LABEL[e.kind] ?? e.kind.replace(/_/g, ' ');
}

export function eventTone(e: RegisterEvent): 'danger' | 'warning' | 'success' | 'info' | 'neutral' {
  if (e.kind === 'resolved') return 'success';
  if (e.kind === 'closed') return 'info';
  if (e.to === 'open') return e.verdict === 'inconclusive' ? 'warning' : 'danger';
  return 'neutral';
}

/** The register status an audit event stands for (mirrors the backend's `event_status`). */
export function eventStatus(e: RegisterEvent): RegisterStatus | null {
  switch (e.kind) {
    case 'opened':
    case 'first_seen':
      return 'new';
    case 'still_open':
      return e.to === 'closed' ? 'accepted_risk' : 'still_open';
    case 'verdict_changed':
      return 'still_open';
    case 'resolved':
      return 'resolved';
    case 'regressed':
      return 'regressed';
    case 'reopened':
      return e.audit_id ? 'regressed' : null;
    case 'checked':
      return 'unchanged';
    default:
      return null;
  }
}

/** A sealed finding's register status: what the pipeline stamped, else what the register recorded. */
export function findingRegisterStatus(
  f: Pick<SealedFinding, 'audit_id' | 'obligation_id' | 'data'>,
  byObligation: Map<string, RegisterItem>,
): RegisterStatus | null {
  const item = byObligation.get(f.obligation_id);
  const event = item?.history.find((e) => e.audit_id === f.audit_id);
  if (event) return eventStatus(event);
  const stamped = f.data?.register_status;
  return typeof stamped === 'string' && stamped in STATUS_META ? (stamped as RegisterStatus) : null;
}

export function byObligation(items: RegisterItem[] | undefined): Map<string, RegisterItem> {
  return new Map((items ?? []).map((i) => [i.obligation_id, i]));
}

// ---- view: label, chapter, facets, filtering ----------------------------------------------

const asFinding = (i: RegisterItem) => ({
  obligation_id: i.obligation_id,
  data: i.article ? { article: i.article } : {},
});

export function itemArticle(i: RegisterItem): string {
  return articleLabel(asFinding(i)) ?? i.obligation_id;
}

export function itemChapter(i: RegisterItem): string {
  return chapterOf(asFinding(i));
}

/** The facet key of an item's state ("Needs review" splits off open + inconclusive). */
export function stateKey(i: Pick<RegisterItem, 'state' | 'verdict'>): string {
  return i.state === 'open' && i.verdict === 'inconclusive' ? 'needs_review' : i.state;
}

export const STATE_KEYS = ['open', 'needs_review', 'closed', 'resolved', 'monitoring'] as const;

export function stateKeyTone(k: string): Tone {
  return k === 'needs_review' ? 'warning' : (STATE_META[k]?.tone ?? 'neutral');
}

export function stateKeyLabel(k: string): string {
  return k === 'needs_review' ? 'Needs review' : (STATE_META[k]?.label ?? k);
}

export interface RegisterFilter {
  query: string;
  states: string[];
  verdicts: string[];
  severities: string[];
  chapters: string[];
}

export function filterItems(items: RegisterItem[], f: RegisterFilter): RegisterItem[] {
  const q = f.query.trim().toLowerCase();
  return items.filter((i) => {
    if (f.states.length && !f.states.includes(stateKey(i))) return false;
    if (f.verdicts.length && !f.verdicts.includes(i.verdict)) return false;
    if (f.severities.length && !f.severities.includes(i.severity ?? 'none')) return false;
    if (f.chapters.length && !f.chapters.includes(itemChapter(i))) return false;
    if (!q) return true;
    const hay = [itemArticle(i), i.obligation_id, i.title, i.gap_id, i.close_reason, i.last_reasoning]
      .filter(Boolean)
      .join(' ')
      .toLowerCase();
    return q.split(/\s+/).every((t) => hay.includes(t));
  });
}

const STATE_RANK: Record<string, number> = {
  open: 0,
  needs_review: 1,
  closed: 2,
  resolved: 3,
  monitoring: 4,
};

/** Open first (worst severity first), then review, accepted, resolved, monitoring. */
export function sortItems(items: RegisterItem[]): RegisterItem[] {
  const sev = (i: RegisterItem) => severityMeta(i.severity)?.rank ?? 5;
  return [...items].sort(
    (a, b) =>
      (STATE_RANK[stateKey(a)] ?? 9) - (STATE_RANK[stateKey(b)] ?? 9) ||
      sev(a) - sev(b) ||
      itemArticle(a).localeCompare(itemArticle(b), undefined, { numeric: true }),
  );
}

export function countBy<T>(items: T[], key: (t: T) => string): Map<string, number> {
  const m = new Map<string, number>();
  for (const it of items) m.set(key(it), (m.get(key(it)) ?? 0) + 1);
  return m;
}

/** "7 open gaps · 2 accepted risks · 3 resolved" (only non-zero parts; empty register = ''). */
export function summaryLine(s: RegisterSummary): string {
  const parts: [number, string, string][] = [
    [s.open_gaps, 'open gap', 'open gaps'],
    [s.needs_review, 'needs review', 'need review'],
    [s.accepted_risks, 'accepted risk', 'accepted risks'],
    [s.resolved, 'resolved', 'resolved'],
  ];
  return parts
    .filter(([n]) => n > 0)
    .map(([n, one, many]) => `${n} ${n === 1 ? one : many}`)
    .join(' · ');
}
