// Pure helpers for the risk-classification UI: normalise the backend rows, pick the run to
// show, and turn result codes into plain words.
import type { BadgeTone } from '@/shared/ui';
import type {
  Citation,
  Classification,
  ClassificationEvent,
  ClassificationResult,
  ResultRiskClass,
} from './types';

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => !!v && typeof v === 'object' && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);
const arr = <T>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);
/** Read `snake_case` or `camelCase` (the backend's response casing is not pinned by the plan). */
const pick = (o: Obj, snake: string, camel: string): unknown => (snake in o ? o[snake] : o[camel]);

function toEvent(raw: unknown, i: number): ClassificationEvent {
  const e = isObj(raw) ? raw : {};
  return {
    id: String(e.id ?? i),
    action: str(e.action) ?? 'unknown',
    actor: str(e.actor) ?? '',
    reason: str(e.reason),
    data: isObj(e.data) ? e.data : {},
    at: str(e.at) ?? str(pick(e, 'created_at', 'createdAt')) ?? '',
  };
}

/** Fill the list fields so components never meet `undefined`. */
export function toResult(raw: unknown): ClassificationResult | null {
  if (!isObj(raw)) return null;
  const r = raw as Partial<ClassificationResult> & Obj;
  return {
    ...r,
    risk_class: str(r.risk_class) ?? 'unknown',
    route: str(r.route) ?? 'none',
    role: str(r.role) ?? 'provider',
    reasoning: str(r.reasoning) ?? '',
    art5_screening: arr(r.art5_screening),
    annex_iii_considered: arr(r.annex_iii_considered),
    counter_arguments: arr(r.counter_arguments),
    would_change_if: arr(r.would_change_if),
    uncertainties: arr(r.uncertainties),
    next_steps: arr(r.next_steps),
    citations: arr(r.citations),
    key_dates: arr(r.key_dates),
    needs_human: r.needs_human === true,
    needs_human_reasons: arr(r.needs_human_reasons),
    verifier_problems: arr(r.verifier_problems),
    confidence: typeof r.confidence === 'number' ? r.confidence : 0,
  } as ClassificationResult;
}

export function toClassification(raw: unknown): Classification {
  const c = isObj(raw) ? raw : {};
  const events = arr<unknown>(c.events).map(toEvent);
  return {
    id: String(c.id ?? ''),
    systemId: str(pick(c, 'system_id', 'systemId')) ?? '',
    status: str(c.status) ?? 'running',
    kbVersion: str(pick(c, 'kb_version', 'kbVersion')),
    dossierVersion: (() => {
      const d = pick(c, 'dossier_version', 'dossierVersion');
      return isObj(d) ? (d as Record<string, number>) : {};
    })(),
    input: isObj(c.input) ? c.input : {},
    result: toResult(c.result),
    error: str(c.error),
    traceId: str(pick(c, 'trace_id', 'traceId')),
    previousId: str(pick(c, 'previous_id', 'previousId')),
    createdBy: str(pick(c, 'created_by', 'createdBy')) ?? '',
    createdAt: str(pick(c, 'created_at', 'createdAt')) ?? '',
    updatedAt: str(pick(c, 'updated_at', 'updatedAt')) ?? str(pick(c, 'created_at', 'createdAt')) ?? '',
    events: events.sort((a, b) => a.at.localeCompare(b.at)),
  };
}

export function toClassifications(raw: unknown): Classification[] {
  const list = Array.isArray(raw) ? raw : isObj(raw) ? arr<unknown>(raw.items) : [];
  return list.map(toClassification).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

/** The newest run (the list is newest first). */
export const latestRun = (list: Classification[]): Classification | undefined => list[0];

/** The class in force: the newest approved or stale run (a stale class stays in force, plan Q2). */
export const inForce = (list: Classification[]): Classification | undefined =>
  list.find((c) => c.status === 'approved' || c.status === 'stale');

export const isRunning = (list: Classification[]) => list.some((c) => c.status === 'running');

/** What the header dot says: a proposal waits, or the class in force is stale. */
export function attention(list: Classification[]): 'proposed' | 'stale' | null {
  if (list[0]?.status === 'proposed') return 'proposed';
  if (inForce(list)?.status === 'stale') return 'stale';
  return null;
}

/** The run a re-classify re-does: a stale, rejected or failed latest run; else none. */
export function previousFor(list: Classification[]): string | undefined {
  const last = list[0];
  if (!last) return undefined;
  if (last.status === 'stale' || last.status === 'rejected') return last.id;
  const f = inForce(list);
  return f?.status === 'stale' ? f.id : undefined;
}

export const RISK_LABEL: Record<ResultRiskClass, { label: string; tone: BadgeTone }> = {
  prohibited: { label: 'Prohibited', tone: 'danger' },
  high_risk: { label: 'High risk', tone: 'danger' },
  limited_risk: { label: 'Limited risk', tone: 'warning' },
  minimal_risk: { label: 'Minimal risk', tone: 'success' },
  out_of_scope: { label: 'Not an AI system', tone: 'neutral' },
};

export function riskLabel(risk: string | null | undefined): { label: string; tone: BadgeTone } {
  return (
    RISK_LABEL[(risk ?? '') as ResultRiskClass] ?? {
      label: risk ? risk.replace(/_/g, ' ') : 'Unclassified',
      tone: 'neutral',
    }
  );
}

const ROUTE_LABEL: Record<string, string> = {
  art5: 'Prohibited practice (Art. 5)',
  art6_1_annex_i: 'Via Art. 6(1): Annex I product or safety component',
  art6_2_annex_iii: 'Via Art. 6(2): Annex III area',
  art6_3_exempt: 'Not high risk: Art. 6(3) derogation',
  art50_only: 'Transparency duties only (Art. 50)',
  none: 'No specific AI Act category',
  not_ai_system: 'Not an AI system (Art. 3(1))',
};

/** "Not high risk: Art. 6(3)(a) derogation" when the condition is known. */
export function routeLabel(route: string, condition?: string | null): string {
  if (route === 'art6_3_exempt' && condition) return `Not high risk: Art. 6(3)(${condition}) derogation`;
  return ROUTE_LABEL[route] ?? route.replace(/_/g, ' ');
}

const CONDITION_LABEL: Record<string, string> = {
  a: 'a narrow procedural task',
  b: 'improves the result of a completed human activity',
  c: 'detects decision patterns, does not replace human assessment',
  d: 'a preparatory task to an assessment',
};

export const conditionLabel = (c: string | null | undefined) =>
  c ? `(${c}) ${CONDITION_LABEL[c] ?? ''}`.trim() : '–';

/** Iris's six options → words. */
const IRIS_LABEL: Record<string, string> = {
  prohibited: 'Prohibited',
  high_risk_annex_i: 'High risk (Annex I)',
  high_risk_annex_iii: 'High risk (Annex III)',
  not_high_risk_6_3: 'Not high risk (Art. 6(3))',
  transparency_only: 'Transparency only',
  minimal: 'Minimal',
};

export const irisLabel = (choice: string | null | undefined) =>
  choice ? (IRIS_LABEL[choice] ?? choice.replace(/_/g, ' ')) : '–';

/** 0.82 → "82%". */
export const pct = (v: number | null | undefined) =>
  typeof v === 'number' && Number.isFinite(v) ? `${Math.round(v * 100)}%` : '–';

export function confidenceTone(v: number | null | undefined): BadgeTone {
  if (typeof v !== 'number') return 'neutral';
  return v >= 0.75 ? 'success' : v >= 0.6 ? 'warning' : 'danger';
}

/** A guidance citation is non-binding; the Art. 6 guidelines are still a draft. */
export function citationFlags(c: Citation): { binding: boolean; draft: boolean } {
  return { binding: c.binding !== false && !c.id.startsWith('INT.'), draft: c.status === 'draft' };
}

/** `AIA.ANNEX_III.4.a` → `Annex III 4(a)`, `AIA.6.3` → `Art. 6(3)`, `AIA.5.1.f` → `Art. 5(1)(f)`. */
export function provisionLabel(id: string): string {
  const annex = /^AIA\.ANNEX_([IVX]+)(?:\.(\d+))?(?:\.([a-z]))?/.exec(id);
  if (annex) {
    const [, n, point, letter] = annex;
    return `Annex ${n}${point ? ` ${point}` : ''}${letter ? `(${letter})` : ''}`;
  }
  const art = /^(AIA|OMNIBUS)\.(\d+[a-z]?)((?:\.[0-9a-z]+)*)$/.exec(id);
  if (art) {
    const [, act, n, rest] = art;
    const parts = rest
      .split('.')
      .filter(Boolean)
      .map((p) => `(${p})`)
      .join('');
    return `${act === 'OMNIBUS' ? 'Omnibus ' : ''}Art. ${n}${parts}`;
  }
  return id;
}

/** Why a run went stale: "RC-… changed AIA.6.3" from its `stale` event. */
export function staleReason(c: Classification): string | null {
  const e = [...c.events].reverse().find((x) => x.action === 'stale');
  if (!e) return c.status === 'stale' ? 'A regulation change touched a provision it relied on.' : null;
  if (e.reason) return e.reason;
  const change = str(e.data.change_id);
  const provisions = arr<string>(e.data.provisions);
  if (change && provisions.length) return `${change} changed ${provisions.join(', ')}`;
  if (change) return `${change} touched a provision it relied on`;
  return 'A regulation change touched a provision it relied on.';
}

/** The reason of the run's `rejected` event. */
export function rejectReason(c: Classification): string | null {
  return [...c.events].reverse().find((x) => x.action === 'rejected')?.reason ?? null;
}

/** The progress phase of a running classification, from its elapsed time (the backend sends no steps). */
export function runPhase(elapsedMs: number): 0 | 1 | 2 {
  if (elapsedMs < 3_000) return 0;
  if (elapsedMs < 35_000) return 1;
  return 2;
}

/** "1:05". */
export function formatElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

export const REASON_MAX = 2000;

export interface PreviewEntry {
  id: string;
  label: string;
  summary: string | null;
  applicable: boolean | null;
  reason: string | null;
  in_force_date: string | null;
  in_force_now: boolean | null;
}

/** Reg-memory catalogue rows (`id`, `article: AIA.10.2`, `summary`) + activation → display rows. */
export function previewEntries(items: Record<string, unknown>[]): PreviewEntry[] {
  return items
    .filter(isObj)
    .map((o) => {
      const id = str(o.id) ?? str(o.obligation_id) ?? '?';
      const article = str(o.article);
      return {
        id,
        label: article ? provisionLabel(article) : (str(o.title) ?? id),
        summary: str(o.summary) ?? str(o.title),
        applicable: typeof o.applicable === 'boolean' ? o.applicable : null,
        reason: str(o.reason),
        in_force_date: str(o.in_force_date),
        in_force_now: typeof o.in_force_now === 'boolean' ? o.in_force_now : null,
      };
    })
    .sort((a, b) => Number(b.applicable !== false) - Number(a.applicable !== false));
}
