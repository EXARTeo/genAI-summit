// Sealed findings (backend `schema/findings.py`, snake_case like the pipeline posts them),
// plus the pure helpers the Findings panel, the report and the system Obligations tab share.
import { findingsFromArtifacts } from './adapters';
import type { Artifact, Finding } from './types';

export type SealedVerdict =
  | 'pass'
  | 'partial'
  | 'gap'
  | 'inconclusive'
  | 'not_applicable'
  | 'not_assessable_by_testing';
export type Severity = 'critical' | 'high' | 'medium' | 'low';
export type AnnotationKind = 'contest' | 'accept_risk' | 'remediation_planned' | 'comment';

export interface EvidenceRef {
  path: string;
  sha256?: string | null;
  mlflow_run_id?: string | null;
  experiment_id?: string | null;
  [k: string]: unknown;
}

export interface CitationRef {
  provision_id: string;
  kb_version?: string | null;
  [k: string]: unknown;
}

export interface Annotation {
  id: string;
  finding_id: string;
  kind: AnnotationKind | (string & {});
  body: string;
  actor: string;
  created_at: string;
}

export interface StatusEvent {
  id: string;
  finding_id: string;
  status: string;
  superseded_by?: string | null;
  reason?: string | null;
  data: Record<string, unknown>;
  actor: string;
  created_at: string;
}

export interface JudgeCall {
  verdict?: string;
  rationale?: string;
  confidence?: number | null;
  [k: string]: unknown;
}

/** One finding as the panel renders it: a sealed row, or a legacy artifact finding mapped onto it. */
export interface SealedFinding {
  id: string;
  audit_id: string;
  system_id: string;
  obligation_id: string;
  verdict: SealedVerdict | (string & {});
  severity: Severity | (string & {}) | null;
  gap_id: string | null;
  metrics_ref: unknown;
  evidence_refs: EvidenceRef[];
  citations: CitationRef[];
  kb_version: string | null;
  reasoning: string | null;
  counter_arguments: unknown;
  would_change_if: unknown;
  judges: Record<string, unknown>;
  critic: { upheld?: boolean | null; objection?: string | null; [k: string]: unknown };
  data: Record<string, unknown>;
  prev_hash: string | null;
  hash: string;
  created_by: string;
  created_at: string;
  status: string;
  stale: boolean;
  sealed: boolean;
  annotations: Annotation[];
  status_events: StatusEvent[];
}

export interface AnnotationIn {
  kind: AnnotationKind;
  body: string;
}

export const ANNOTATION_KINDS: {
  value: AnnotationKind;
  label: string;
  tone: 'danger' | 'warning' | 'info' | 'neutral';
}[] = [
  { value: 'comment', label: 'Comment', tone: 'neutral' },
  { value: 'contest', label: 'Contest', tone: 'danger' },
  { value: 'accept_risk', label: 'Accept risk', tone: 'warning' },
  { value: 'remediation_planned', label: 'Remediation planned', tone: 'info' },
];

export function annotationKind(kind: string) {
  return (
    ANNOTATION_KINDS.find((k) => k.value === kind) ?? { value: kind, label: kind, tone: 'neutral' as const }
  );
}

/** Severity order (critical first) and tone. */
export const SEVERITY: Record<
  Severity,
  { rank: number; tone: 'danger' | 'warning' | 'info' | 'neutral'; label: string }
> = {
  critical: { rank: 0, tone: 'danger', label: 'Critical' },
  high: { rank: 1, tone: 'danger', label: 'High' },
  medium: { rank: 2, tone: 'warning', label: 'Medium' },
  low: { rank: 3, tone: 'neutral', label: 'Low' },
};

export function severityMeta(s: string | null | undefined) {
  return s ? (SEVERITY[s as Severity] ?? { rank: 4, tone: 'neutral' as const, label: s }) : null;
}

/** Text lists may arrive as a string, a list of strings, or a list of objects. */
export function textList(v: unknown): string[] {
  if (v == null || v === '') return [];
  if (typeof v === 'string') return [v];
  if (Array.isArray(v))
    return v
      .map((x) =>
        typeof x === 'string'
          ? x
          : x && typeof x === 'object'
            ? String(
                (x as Record<string, unknown>).text ??
                  (x as Record<string, unknown>).argument ??
                  (x as Record<string, unknown>).condition ??
                  JSON.stringify(x),
              )
            : String(x),
      )
      .filter(Boolean);
  return [JSON.stringify(v)];
}

/** A judge's call: `"gap"` or `{verdict, rationale, confidence}`. */
export function judgeCall(v: unknown): JudgeCall | null {
  if (v == null) return null;
  if (typeof v === 'string') return { verdict: v };
  if (typeof v === 'object') {
    const o = v as Record<string, unknown>;
    return {
      ...o,
      verdict: typeof o.verdict === 'string' ? o.verdict : typeof o.call === 'string' ? o.call : undefined,
      rationale:
        typeof o.rationale === 'string' ? o.rationale : typeof o.reason === 'string' ? o.reason : undefined,
      confidence: typeof o.confidence === 'number' ? o.confidence : null,
    };
  }
  return { verdict: String(v) };
}

export const JUDGES = [
  { key: 'rule', label: 'Rule (code)' },
  { key: 'gemini', label: 'Gemini' },
  { key: 'iris', label: 'Oumi Iris' },
] as const;

/** Do the judges that answered agree on one verdict? */
export function judgesAgree(judges: Record<string, unknown>): boolean | null {
  const calls = JUDGES.map((j) => judgeCall(judges[j.key])?.verdict).filter((v): v is string => !!v);
  if (calls.length < 2) return null;
  return calls.every((c) => c === calls[0]);
}

/** The obligation's article label: `data.article`, else derived from the id (`OBL.AIA.10.2.f` → Art. 10(2)(f)). */
export function articleOf(f: Pick<SealedFinding, 'obligation_id' | 'data'>): string | null {
  const a = f.data?.article;
  if (typeof a === 'string' && a) return a;
  const m = /AIA\.(\d+[a-z]?)((?:\.[^.]+)*)/i.exec(f.obligation_id);
  if (!m) return null;
  // Paragraph and point tokens only: `OBL.AIA.10.2.f.bias-examination` → 10(2)(f).
  const parts: string[] = [];
  for (const p of m[2].split('.').filter(Boolean)) {
    if (!/^(\d+|[a-z]{1,2})$/i.test(p)) break;
    parts.push(p);
  }
  return `Art. ${m[1]}${parts.map((p) => `(${p})`).join('')}`;
}

export function titleOf(f: Pick<SealedFinding, 'data'>): string | null {
  const t = f.data?.title ?? f.data?.obligation_title;
  return typeof t === 'string' && t ? t : null;
}

const LEGACY_VERDICT: Record<string, SealedVerdict> = {
  supports_compliance: 'pass',
  indicates_gap: 'gap',
};

/** A legacy artifact finding mapped onto the sealed shape (shown when no sealed rows exist yet). */
export function legacyToSealed(f: Finding, auditId: string, systemId: string): SealedFinding {
  return {
    id: f.id,
    audit_id: auditId,
    system_id: systemId,
    obligation_id: f.requirement ?? f.id,
    verdict: LEGACY_VERDICT[f.verdict] ?? f.verdict,
    severity: null,
    gap_id: null,
    metrics_ref: f.metric ?? null,
    evidence_refs: f.evidence
      .filter((e) => e.runId)
      .map((e) => ({ path: e.text, mlflow_run_id: e.runId ?? null })),
    citations: f.citations.map((c) => ({ provision_id: c.provision, kb_version: c.kbVersion ?? null })),
    kb_version: f.citations.find((c) => c.kbVersion)?.kbVersion ?? null,
    reasoning: f.reasoning ?? null,
    counter_arguments: f.counterEvidence,
    would_change_if: f.wouldChangeIf,
    judges: {},
    critic: f.critic
      ? { upheld: !f.critic.adjusted, objection: f.critic.note ?? null, call: f.critic.call }
      : {},
    data: { title: f.title, evidence: f.evidence.map((e) => e.text), confidence: f.confidence },
    prev_hash: null,
    hash: '',
    created_by: 'agent',
    created_at: '',
    status: 'current',
    stale: false,
    sealed: false,
    annotations: [],
    status_events: [],
  };
}

/** Sealed rows when there are any, else the audit's finding artifacts (older audits). */
export function panelFindings(
  sealed: SealedFinding[] | undefined,
  artifacts: Artifact[],
  auditId: string,
  systemId: string,
): SealedFinding[] {
  if (sealed && sealed.length > 0) return sealed;
  return findingsFromArtifacts(artifacts).map((f) => legacyToSealed(f, auditId, systemId));
}

/** Gaps first (by severity), then the rest by obligation id. */
export function sortFindings(rows: SealedFinding[]): SealedFinding[] {
  const weight = (f: SealedFinding) => severityMeta(f.severity)?.rank ?? (isGapLike(f.verdict) ? 4 : 9);
  return [...rows].sort((a, b) => weight(a) - weight(b) || a.obligation_id.localeCompare(b.obligation_id));
}

export function isGapLike(verdict: string): boolean {
  return verdict === 'gap' || verdict === 'partial' || verdict === 'indicates_gap';
}

export interface GapRow {
  gapId: string;
  obligationId: string;
  article: string | null;
  severity: string | null;
  verdict: string;
  inForce: string | null;
  remediation: string | null;
}

/** The gap list (plan 01 §8): every finding with a gap id, or a gap-like verdict. */
export function gapList(rows: SealedFinding[]): GapRow[] {
  return sortFindings(rows)
    .filter((f) => f.gap_id || isGapLike(f.verdict) || f.verdict === 'inconclusive')
    .map((f, i) => ({
      gapId: f.gap_id ?? `G-${String(i + 1).padStart(2, '0')}`,
      obligationId: f.obligation_id,
      article: articleOf(f),
      severity: f.severity,
      verdict: f.verdict,
      inForce: typeof f.data.in_force_date === 'string' ? f.data.in_force_date : null,
      remediation:
        typeof f.data.remediation === 'string'
          ? f.data.remediation
          : (textList(f.would_change_if)[0] ?? null),
    }));
}

export interface EvidenceRow {
  obligationId: string;
  verdict: string;
  hash: string;
  evidence: EvidenceRef[];
  citations: CitationRef[];
}

/** The evidence register (plan 01 §8): verdict → evidence files, MLflow runs, provisions at kb. */
export function evidenceRegister(rows: SealedFinding[]): EvidenceRow[] {
  return [...rows]
    .sort((a, b) => a.obligation_id.localeCompare(b.obligation_id))
    .map((f) => ({
      obligationId: f.obligation_id,
      verdict: f.verdict,
      hash: f.hash,
      evidence: f.evidence_refs,
      citations: f.citations,
    }));
}

// ---- obligation map (artifact `obligation_map`) ---------------------------------------------

export interface ObligationEntry {
  obligation_id: string;
  article?: string | null;
  title?: string | null;
  applicable: boolean | null;
  reason?: string | null;
  in_force_date?: string | null;
  in_force_now?: boolean | null;
  verification_mode?: string | null;
  decided_by?: string | null;
}

const asStr = (v: unknown) => (typeof v === 'string' && v ? v : null);
const asBool = (v: unknown) => (typeof v === 'boolean' ? v : null);

/** Entries from an `obligation_map` artifact's data (`{entries}`, `{obligations}` or a bare list). */
export function obligationEntries(data: unknown): ObligationEntry[] {
  const d = data as Record<string, unknown> | unknown[] | null;
  const raw = Array.isArray(d)
    ? d
    : d && typeof d === 'object'
      ? ((d.entries ?? d.obligations ?? d.map ?? []) as unknown[])
      : [];
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((e): e is Record<string, unknown> => !!e && typeof e === 'object')
    .map((e) => ({
      obligation_id: asStr(e.obligation_id) ?? asStr(e.id) ?? '?',
      article: asStr(e.article),
      title: asStr(e.title),
      applicable: asBool(e.applicable),
      reason: asStr(e.reason),
      in_force_date: asStr(e.in_force_date),
      in_force_now: asBool(e.in_force_now),
      verification_mode: asStr(e.verification_mode),
      decided_by: asStr(e.decided_by),
    }));
}

/** The latest live `obligation_map` artifact of an audit. */
export function obligationMapArtifact(artifacts: Artifact[]): Artifact | null {
  return (
    artifacts
      .filter((a) => a.kind === 'obligation_map' && a.status !== 'superseded')
      .sort((a, b) => b.version - a.version)[0] ?? null
  );
}

/** Short hash for display (`ab12cd34…`). */
export function shortHash(h: string | null | undefined, n = 10): string {
  return h ? (h.length > n ? `${h.slice(0, n)}…` : h) : '–';
}
