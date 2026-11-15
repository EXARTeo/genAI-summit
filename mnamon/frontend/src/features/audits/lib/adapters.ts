// Artifact adapters: the one place that maps an artifact's `data` (the snake_case shapes the
// pipeline writes, mnamon/agents/pipeline/{graph,schemas}.py, or the older mock shapes) onto the
// view models in ./types. Every field is parsed leniently with Zod: a missing or malformed field
// becomes undefined / null / [] and the views render "–"; an adapter never throws.
import { z } from 'zod';
import type {
  Artifact,
  ContextData,
  CriticData,
  DatasetAnalysisData,
  DatasetData,
  Finding,
  FindingsData,
  GateName,
  GateResult,
  GateStatus,
  GenerationSpecData,
  ModelProfileData,
  PublicCandidatesData,
  ReportData,
  ReviewVerdict,
  Scenario,
  ScenarioReview,
  ScenarioAnalysisData,
  ScenariosData,
  TestResultsData,
  TwinModeSummary,
  TwinPair,
} from './types';

// ---- lenient primitives ------------------------------------------------------

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => !!v && typeof v === 'object' && !Array.isArray(v);

const str = z.preprocess(
  (v) =>
    typeof v === 'string' ? v : typeof v === 'number' || typeof v === 'boolean' ? String(v) : undefined,
  z.string().optional(),
);
const num = z.preprocess((v) => {
  if (typeof v === 'number') return Number.isFinite(v) ? v : undefined;
  if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) return Number(v);
  return undefined;
}, z.number().optional());
const bool = z.preprocess((v) => (typeof v === 'boolean' ? v : undefined), z.boolean().optional());
const strList = z.preprocess(
  (v) =>
    Array.isArray(v)
      ? v.filter((x) => typeof x === 'string' || typeof x === 'number').map((x) => String(x))
      : [],
  z.array(z.string()),
);
const ci = z.preprocess(
  (v) =>
    Array.isArray(v) && v.length >= 2 && typeof v[0] === 'number' && typeof v[1] === 'number'
      ? [v[0], v[1]]
      : undefined,
  z.tuple([z.number(), z.number()]).optional(),
);
const record = z.preprocess((v) => (isObj(v) ? v : {}), z.record(z.unknown()));

function obj<T extends z.ZodRawShape>(shape: T) {
  return z.preprocess((v) => (isObj(v) ? v : {}), z.object(shape).passthrough());
}
function list<T extends z.ZodTypeAny>(item: T) {
  return z.preprocess((v) => (Array.isArray(v) ? v : []), z.array(item));
}
/** Parse, falling back to the schema's empty value (never throws). */
function parse<S extends z.ZodTypeAny>(schema: S, v: unknown): z.output<S> {
  const r = schema.safeParse(v);
  return r.success ? r.data : schema.parse({});
}

const asObj = (v: unknown): Obj => (isObj(v) ? v : {});
const first = <T>(...vals: (T | undefined | null)[]): T | undefined =>
  vals.find((v) => v !== undefined && v !== null) ?? undefined;

/** ">= 0.80" -> 0.8 */
export function thresholdNumber(text?: string): number | undefined {
  const m = text?.match(/-?\d+(\.\d+)?/);
  return m ? Number(m[0]) : undefined;
}

// ---- context -----------------------------------------------------------------

const RawContext = obj({
  system: obj({
    id: str,
    name: str,
    role: str,
    annex: str,
    annex_basis: str,
    risk_class: str,
    intendedPurpose: str,
    intended_purpose: str,
  }),
  requirements: list(
    obj({
      id: str,
      title: str,
      provision: str,
      testable: bool,
      source: str,
      obligation: str,
      testability: str,
    }),
  ),
  plugins: list(z.unknown()),
  filesRead: list(obj({ path: str, version: num })),
  files_read: list(obj({ path: str, version: num })),
  testable: strList,
  kb_version: str,
  target: str,
});

export function toContext(data: unknown): ContextData {
  const d = parse(RawContext, data);
  const testable = new Set(d.testable);
  return {
    system: {
      id: d.system.id,
      name: d.system.name,
      role: d.system.role,
      annex: first(d.system.annex, d.system.annex_basis),
      riskClass: d.system.risk_class,
      intendedPurpose: first(d.system.intendedPurpose, d.system.intended_purpose),
    },
    requirements: d.requirements
      .filter((r) => r.id)
      .map((r) => ({
        id: r.id!,
        title: first(r.title, r.obligation),
        provision: first(r.provision, r.source),
        testable: r.testable ?? (testable.has(r.id!) || r.testability === 'model_and_data_test'),
      })),
    plugins: d.plugins.flatMap((p) => {
      if (typeof p === 'string') return [{ name: p }];
      const o = asObj(p);
      const name = parse(str, o.name ?? o.id);
      if (!name) return [];
      return [
        {
          name,
          accessType: parse(str, o.accessType ?? o.access_type),
          placement: parse(str, o.placement),
        },
      ];
    }),
    filesRead: [...d.filesRead, ...d.files_read]
      .filter((f) => f.path)
      .map((f) => ({ path: f.path!, version: f.version })),
    kbVersion: d.kb_version,
    target: d.target,
  };
}

// ---- model profile -------------------------------------------------------------

const MockProfile = obj({
  model: obj({ name: str, version: str, flavor: str, metrics: record }),
  sensitivity: list(obj({ feature: str, score: num, protectedProxy: bool, note: str })),
  boundary: list(obj({ feature: str, threshold: str, flipRate: num, note: str })),
  probes: num,
  notes: strList,
});

const RealSensitivity = obj({
  role: str,
  proxy_for: strList,
  moves_output: bool,
  oat_flip_rate: num,
  oat_mean_range: num,
  perm_mean_abs_delta: num,
  mean_range: num,
  flip_rate: num,
});

const RealProfile = obj({
  target: obj({ name: str, plugin: str, access_type: str }),
  generator: str,
  sensitivity: record,
  probes: obj({ n: num }),
  notes: strList,
  output: obj({ positive_rate: num, threshold: num }),
  decision_boundary: obj({
    threshold: num,
    band: num,
    near_share: num,
    surrogate: obj({ r2: num }),
  }),
});

export function toModelProfile(data: unknown): ModelProfileData {
  const raw = asObj(data);
  if (!isObj(raw.profile) && Array.isArray(raw.sensitivity)) {
    const d = parse(MockProfile, raw);
    return {
      model: {
        name: d.model.name,
        version: d.model.version,
        flavor: d.model.flavor,
        metrics: Object.fromEntries(
          Object.entries(d.model.metrics).filter((e): e is [string, number] => typeof e[1] === 'number'),
        ),
      },
      sensitivity: d.sensitivity
        .filter((s) => s.feature)
        .map((s) => ({
          feature: s.feature!,
          score: s.score ?? 0,
          protectedProxy: s.protectedProxy,
          note: s.note,
        })),
      boundary: d.boundary
        .filter((b) => b.feature)
        .map((b) => ({
          feature: b.feature!,
          threshold: b.threshold,
          flipRate: b.flipRate ?? null,
          note: b.note,
        })),
      probes: d.probes,
      notes: d.notes,
    };
  }
  const p = parse(RealProfile, raw.profile ?? raw);
  const db = p.decision_boundary;
  const boundaryText =
    db.threshold != null ? `${db.threshold}${db.band != null ? ` ± ${db.band}` : ''}` : undefined;
  const features = Object.entries(p.sensitivity).map(([feature, s]) => ({
    feature,
    s: parse(RealSensitivity, s),
  }));
  const note = (s: z.output<typeof RealSensitivity>) =>
    s.proxy_for.length ? `proxy for ${s.proxy_for.join(', ')}` : s.role;
  const metrics: Record<string, number> = {};
  if (p.output.positive_rate != null) metrics.positive_rate = p.output.positive_rate;
  if (db.surrogate.r2 != null) metrics.surrogate_r2 = db.surrogate.r2;
  if (db.near_share != null) metrics.near_boundary = db.near_share;
  return {
    model: { name: first(p.target.name, p.target.plugin), flavor: p.target.access_type, metrics },
    sensitivity: features.map(({ feature, s }) => ({
      feature,
      score: first(s.oat_mean_range, s.mean_range, s.perm_mean_abs_delta) ?? 0,
      protectedProxy: s.role === 'proxy' || s.proxy_for.length > 0,
      note: note(s),
    })),
    boundary: features
      .filter(({ s }) => (first(s.oat_flip_rate, s.flip_rate) ?? 0) > 0)
      .sort((a, b) => (b.s.oat_flip_rate ?? 0) - (a.s.oat_flip_rate ?? 0))
      .map(({ feature, s }) => ({
        feature,
        threshold: boundaryText,
        flipRate: first(s.oat_flip_rate, s.flip_rate) ?? null,
        note: note(s),
      })),
    probes: p.probes.n,
    notes: p.notes,
  };
}

// ---- public dataset candidates ---------------------------------------------------

const RawCandidates = obj({
  plugin: str,
  candidates: list(
    obj({
      id: str,
      name: str,
      url: str,
      source: str,
      score: num,
      n_rows: num,
      task: str,
      fetchable: bool,
      licence: z.unknown(),
      mapping: record,
      protected_missing: strList,
      description: str,
    }),
  ),
  recommendation: obj({ mode: str, reason: str, candidate: z.unknown() }),
  sources: record,
});

export function toPublicCandidates(data: unknown): PublicCandidatesData {
  const d = parse(RawCandidates, data);
  const rec = d.recommendation;
  const recCandidate = isObj(rec.candidate) ? parse(str, rec.candidate.id) : parse(str, rec.candidate);
  return {
    plugin: d.plugin,
    candidates: d.candidates
      .filter((c) => c.id)
      .map((c) => {
        const licence = isObj(c.licence) ? c.licence : {};
        return {
          id: c.id!,
          name: c.name ?? c.id!,
          url: c.url,
          source: c.source,
          score: c.score ?? null,
          rows: c.n_rows,
          task: c.task,
          fetchable: c.fetchable ?? false,
          licence: parse(str, licence.normalised ?? licence.raw) ?? parse(str, c.licence),
          licenceStatus: parse(str, licence.status),
          mapped: Object.keys(c.mapping),
          missingProtected: c.protected_missing,
          description: c.description?.replace(/\s+/g, ' ').trim() || undefined,
        };
      }),
    recommendation: { mode: rec.mode, reason: rec.reason, candidate: recCandidate ?? null },
    sources: Object.entries(d.sources).map(([name, s]) => {
      const o = parse(obj({ ok: bool, found: num, error: str }), s);
      return { name, ok: o.ok ?? false, found: o.found, error: o.error };
    }),
  };
}

// ---- scenarios ------------------------------------------------------------------

const PRIORITIES = ['high', 'medium', 'low'] as const;
type Priority = (typeof PRIORITIES)[number];

const RawScenarios = obj({
  scenarios: list(
    obj({
      id: str,
      title: str,
      template: str,
      requirement: str,
      groups: strList,
      n: num,
      priority: str,
      rationale: str,
      metric: str,
      obligation_id: str,
      obligationId: str,
      expected_behaviour: str,
      protected: strList,
      proxies: strList,
      data_needs: obj({ n: num, attribute: str, fields: strList }),
      memory_applied: strList,
      memoryApplied: strList,
      review: z.unknown(),
    }),
  ),
  not_testable: strList,
  assumptions: z.unknown(),
  approved_ids: strList,
  approvedIds: strList,
  excluded: list(obj({ id: str, reason: str, obligation_id: str, obligationId: str, metric: str })),
});

const REVIEW_VERDICTS: ReviewVerdict[] = ['relevant', 'needs_change', 'not_relevant'];

/** The scenario judge's review (agents analyse_scenarios step); undefined when absent or malformed. */
export function toScenarioReview(raw: unknown): ScenarioReview | undefined {
  if (!isObj(raw)) return undefined;
  const r = parse(
    obj({
      model: str,
      verdict: str,
      rationale: str,
      suggested_change: str,
      suggestedChange: str,
      confidence: num,
    }),
    raw,
  );
  if (!REVIEW_VERDICTS.includes(r.verdict as ReviewVerdict)) return undefined;
  return {
    model: (r.model ?? 'gemini').toLowerCase(),
    verdict: r.verdict as ReviewVerdict,
    rationale: r.rationale,
    suggestedChange: first(r.suggested_change, r.suggestedChange) ?? null,
    confidence: r.confidence ?? null,
  };
}

const REVIEW_ORDER: Record<ReviewVerdict, number> = { not_relevant: 0, needs_change: 1, relevant: 2 };

/** Scenarios with a review, not_relevant and needs_change first (the gate drawer's order). */
export function reviewedScenarios(data: ScenariosData): (Scenario & { review: ScenarioReview })[] {
  return data.scenarios
    .filter((s): s is Scenario & { review: ScenarioReview } => !!s.review)
    .sort(
      (a, b) => REVIEW_ORDER[a.review.verdict] - REVIEW_ORDER[b.review.verdict] || a.id.localeCompare(b.id),
    );
}

export function toScenarios(data: unknown): ScenariosData {
  const d = parse(RawScenarios, data);
  return {
    scenarios: d.scenarios
      .filter((s) => s.id)
      .map((s) => ({
        id: s.id!,
        title: first(s.title, s.expected_behaviour),
        template: s.template,
        requirement: s.requirement,
        groups: s.groups.length ? s.groups : [...s.protected, ...s.proxies],
        n: first(s.n, s.data_needs.n),
        priority: PRIORITIES.includes(s.priority as Priority) ? (s.priority as Priority) : undefined,
        rationale: s.rationale,
        metric: s.metric,
        obligationId: first(s.obligation_id, s.obligationId),
        memoryApplied: [...s.memory_applied, ...s.memoryApplied],
        review: toScenarioReview(s.review),
      })),
    notTestable: d.not_testable,
    assumptions: parse(strList, d.assumptions),
    ...(d.approved_ids.length || d.approvedIds.length
      ? { approvedIds: d.approved_ids.length ? d.approved_ids : d.approvedIds }
      : {}),
    ...(d.excluded.some((x) => x.id)
      ? {
          excluded: d.excluded
            .filter((x) => x.id)
            .map((x) => ({
              id: x.id!,
              reason: x.reason || 'excluded by the reviewer',
              obligationId: first(x.obligation_id, x.obligationId),
              metric: x.metric,
            })),
        }
      : {}),
  };
}

const CoverageStatus = ['covered', 'partial', 'not_testable'] as const;

const RawScenarioAnalysis = obj({
  // mock shape
  coverage: z.unknown(),
  risks: strList,
  notTestable: list(obj({ requirement: str, why: str })),
  diff: z.unknown(),
  summary: str,
  // real shape
  analysis: obj({
    status: str,
    n_scenarios: num,
    missing: list(obj({ what: str, why: str, priority: str })),
    coverage: obj({ protected: record, proxies: record, monotone: record }),
    scenarios: list(obj({ id: str, requirement: str, status: str, issues: strList })),
  }),
  not_testable: strList,
});

export function toScenarioAnalysis(data: unknown): ScenarioAnalysisData {
  const d = parse(RawScenarioAnalysis, data);
  const a = d.analysis;
  const mockCoverage = Array.isArray(d.coverage)
    ? parse(list(obj({ requirement: str, scenarios: strList, status: str })), d.coverage)
        .filter((c) => c.requirement)
        .map((c) => ({
          requirement: c.requirement!,
          scenarios: c.scenarios,
          status: CoverageStatus.includes(c.status as never)
            ? (c.status as (typeof CoverageStatus)[number])
            : ('partial' as const),
        }))
    : [];
  const byReq = new Map<string, { scenarios: string[]; ok: boolean }>();
  for (const s of a.scenarios) {
    if (!s.requirement) continue;
    const row = byReq.get(s.requirement) ?? { scenarios: [], ok: true };
    if (s.id) row.scenarios.push(s.id);
    row.ok &&= (s.status ?? 'ok') === 'ok' && s.issues.length === 0;
    byReq.set(s.requirement, row);
  }
  const realCoverage = [...byReq].map(([requirement, r]) => ({
    requirement,
    scenarios: r.scenarios,
    status: r.ok ? ('covered' as const) : ('partial' as const),
  }));
  const issues = a.scenarios.flatMap((s) => s.issues.map((i) => `${s.id ?? '?'}: ${i}`));
  const missing = a.missing.map(
    (m) => `${m.priority ? `${m.priority}: ` : ''}${m.what ?? 'missing test'}${m.why ? ` (${m.why})` : ''}`,
  );
  const attr = (kind: string, rec: Obj) =>
    Object.entries(rec).map(([name, covered]) => ({ name, kind, covered: covered === true }));
  const diff = isObj(d.diff)
    ? {
        added: parse(strList, d.diff.added),
        removed: parse(strList, d.diff.removed),
        changed: parse(strList, d.diff.changed),
      }
    : undefined;
  const realSummary =
    a.n_scenarios != null || a.status
      ? `${a.n_scenarios ?? a.scenarios.length} scenarios checked · status ${a.status ?? '–'}${
          a.missing.length ? ` · ${a.missing.length} missing` : ''
        }`
      : undefined;
  return {
    coverage: mockCoverage.length ? mockCoverage : realCoverage,
    risks: [...d.risks, ...missing, ...issues],
    notTestable: [
      ...d.notTestable.filter((n) => n.requirement).map((n) => ({ requirement: n.requirement!, why: n.why })),
      ...d.not_testable.map((requirement) => ({ requirement })),
    ],
    diff,
    summary: first(d.summary, realSummary),
    attributeCoverage: [
      ...attr('protected', a.coverage.protected),
      ...attr('proxy', a.coverage.proxies),
      ...attr('monotone', a.coverage.monotone),
    ],
  };
}

// ---- generation spec -------------------------------------------------------------

const RawSpec = obj({
  testSpec: str,
  yaml: str,
  spec_yaml: str,
  mode: str,
  assumptions: list(obj({ field: str, what: str, item: str, note: str, provenance: str })),
  diff: z.unknown(),
  problems: strList,
  rationale: str,
  parsed: obj({ name: str }),
});

export function toGenerationSpec(data: unknown): GenerationSpecData {
  const d = parse(RawSpec, data);
  const diff = Array.isArray(d.diff)
    ? parse(list(obj({ field: str, before: str, after: str, provenance: str })), d.diff)
        .filter((x) => x.field)
        .map((x) => ({
          field: x.field!,
          before: x.before ?? '–',
          after: x.after ?? '–',
          provenance: (x.provenance ??
            'llm_assumption') as GenerationSpecData['assumptions'][number]['provenance'] &
            NonNullable<GenerationSpecData['diff']>[number]['provenance'],
        }))
    : undefined;
  return {
    testSpec: first(d.testSpec, d.parsed.name),
    yaml: first(d.yaml, d.spec_yaml) ?? '',
    mode: d.mode,
    assumptions: d.assumptions
      .map((a) => ({
        field: first(a.field, a.item) ?? '–',
        what: first(a.what, a.note),
        provenance: a.provenance ?? 'llm_assumption',
      }))
      .filter((a) => a.field !== '–' || a.what),
    diff,
    problems: d.problems,
    rationale: d.rationale,
  };
}

// ---- dataset analysis ---------------------------------------------------------------

const GATES: GateName[] = ['schema', 'business_rules', 'realism', 'coverage', 'privacy'];
const GATE_STATUSES: GateStatus[] = ['pass', 'warn', 'fail'];
const TWIN_MODES: Record<string, { mode: string; label: string; description: string }> = {
  attribute_only: { mode: 'a', label: 'Attribute only', description: 'Flip the protected attribute alone' },
  causal: { mode: 'b', label: 'Causal', description: 'Flip it and re-sample what depends on it' },
  proxy_only: { mode: 'c', label: 'Proxy only', description: 'Change only the proxies, keep the attribute' },
};

function toGate(raw: unknown): GateResult | undefined {
  if (!isObj(raw)) return undefined;
  const status = parse(str, raw.status);
  if (!GATE_STATUSES.includes(status as GateStatus)) return undefined;
  const metrics: Record<string, number | string | boolean> = {};
  const src = isObj(raw.metrics) ? raw.metrics : raw;
  for (const [k, v] of Object.entries(src)) {
    if (k === 'status' || k === 'note' || k === 'problems') continue;
    if (typeof v === 'number' || typeof v === 'boolean') metrics[k] = v;
    else if (typeof v === 'string' && v.length <= 40) metrics[k] = v;
  }
  const problems = parse(strList, raw.problems);
  const note = parse(str, raw.note);
  return {
    status: status as GateStatus,
    metrics: Object.keys(metrics).length ? metrics : undefined,
    note: problems.length ? problems.slice(0, 3).join('; ') : note || undefined,
  };
}

function realCoverage(raw: unknown): DatasetAnalysisData['coverage'] {
  const c = parse(obj({ cells: strList, min_per_cell: num, counts: record }), raw);
  const entries = Object.entries(c.counts).filter((e): e is [string, number] => typeof e[1] === 'number');
  const rows: string[] = [];
  const cols: string[] = [];
  const split = (k: string) => {
    const [r, col = 'rows'] = k.split('|');
    return [r, col] as const;
  };
  for (const [k] of entries) {
    const [r, col] = split(k);
    if (!rows.includes(r)) rows.push(r);
    if (!cols.includes(col)) cols.push(col);
  }
  const counts = rows.map(() => cols.map(() => 0));
  for (const [k, n] of entries) {
    const [r, col] = split(k);
    counts[rows.indexOf(r)][cols.indexOf(col)] = n;
  }
  return { rows, cols, counts, minPerCell: c.min_per_cell ?? 0, label: c.cells.join(' × ') || undefined };
}

export function toDatasetAnalysis(data: unknown): DatasetAnalysisData {
  const raw = asObj(data);
  if (!isObj(raw.analysis)) {
    // Mock shape (already the view model); still guard every field.
    const cov = asObj(raw.coverage);
    const gates: DatasetAnalysisData['gates'] = {};
    for (const g of GATES) {
      const r = toGate(asObj(raw.gates)[g]);
      if (r) gates[g] = r;
    }
    return {
      datasetId: parse(str, raw.datasetId),
      name: parse(str, raw.name),
      rows: parse(num, raw.rows),
      pairs: parse(num, raw.pairs),
      gates,
      coverage: {
        rows: parse(strList, cov.rows),
        cols: parse(strList, cov.cols),
        counts: Array.isArray(cov.counts)
          ? cov.counts.map((r) => (Array.isArray(r) ? r.map((n) => (typeof n === 'number' ? n : 0)) : []))
          : [],
        minPerCell: parse(num, cov.minPerCell) ?? 0,
        label: parse(str, cov.label),
      },
      twinModes: parse(
        list(obj({ mode: str, label: str, description: str, flipRate: num, meanDelta: num, ci })),
        raw.twinModes,
      ).map((t) => ({
        mode: t.mode ?? '?',
        label: t.label ?? t.mode ?? '–',
        description: t.description,
        flipRate: t.flipRate ?? null,
        meanDelta: t.meanDelta ?? null,
        ci: t.ci ?? null,
      })),
      twins: (Array.isArray(raw.twins) ? raw.twins : []).filter(
        (t): t is TwinPair => isObj(t) && isObj(t.base) && isObj(t.twin) && typeof t.pairId === 'string',
      ),
      limitations: parse(strList, raw.limitations),
    };
  }
  const a = parse(
    obj({
      gates: record,
      dataset: obj({ rows: num }),
      twin_validity: record,
    }),
    raw.analysis,
  );
  const card = parse(obj({ dataset_id: str, name: str, limitations: z.unknown() }), raw.data_card);
  const gates: DatasetAnalysisData['gates'] = {};
  for (const g of GATES) {
    const r = toGate(a.gates[g]);
    if (r) gates[g] = r;
  }
  const twinModes: TwinModeSummary[] = Object.entries(a.twin_validity).map(([mode, v]) => {
    const t = parse(obj({ pairs: num, valid_share: num }), v);
    const meta = TWIN_MODES[mode] ?? { mode, label: mode, description: '' };
    return {
      mode: meta.mode,
      label: meta.label,
      description: meta.description,
      flipRate: null,
      meanDelta: null,
      ci: null,
      pairs: t.pairs,
      validShare: t.valid_share ?? null,
    };
  });
  twinModes.sort((x, y) => x.mode.localeCompare(y.mode));
  const limitations = Array.isArray(card.limitations)
    ? card.limitations.map((l) =>
        typeof l === 'string'
          ? l
          : isObj(l)
            ? (parse(str, l.text ?? l.what) ?? JSON.stringify(l))
            : String(l),
      )
    : [];
  return {
    datasetId: card.dataset_id,
    name: card.name,
    rows: a.dataset.rows,
    pairs: twinModes.length ? twinModes.reduce((n, t) => n + (t.pairs ?? 0), 0) : undefined,
    gates,
    coverage: realCoverage(a.gates.coverage),
    twinModes,
    twins: [],
    limitations,
  };
}

// ---- dataset (generate_data) -----------------------------------------------------------

const numRecord = (v: unknown): Record<string, number> =>
  Object.fromEntries(
    Object.entries(isObj(v) ? v : {}).filter((e): e is [string, number] => typeof e[1] === 'number'),
  );

export function toDataset(data: unknown): DatasetData {
  const raw = asObj(data);
  const card = asObj(raw.data_card);
  const gen = asObj(card.generation);
  const comp = asObj(card.composition);
  const sampleRows = (Array.isArray(card.sample_rows) ? card.sample_rows : []).filter(isObj).slice(0, 5);
  const columns = [...new Set(sampleRows.flatMap((r) => Object.keys(r)))].filter((c) => !c.startsWith('_'));
  return {
    datasetId: parse(str, card.dataset_id),
    name: parse(str, card.name),
    rows: parse(num, comp.rows),
    mode: parse(str, gen.mode),
    method: parse(str, gen.method),
    seed: parse(num, first(gen.seed, raw.seed)),
    byTest: numRecord(comp.by_test),
    twinsByMode: numRecord(comp.twins_by_mode),
    population: Object.entries(asObj(card.population)).map(([stat, v]) => {
      const o = parse(obj({ stated: num, observed: num, within_tolerance: bool }), v);
      return { stat, stated: o.stated, observed: o.observed, ok: o.within_tolerance ?? null };
    }),
    limitations: parse(strList, card.limitations),
    sample: {
      columns,
      rows: sampleRows.map((r) =>
        Object.fromEntries(
          columns.map((c) => [c, typeof r[c] === 'number' ? (r[c] as number) : String(r[c] ?? '–')]),
        ),
      ),
    },
    status: parse(str, raw.status),
    problems: parse(strList, raw.problems),
  };
}

// ---- test results ---------------------------------------------------------------------

const RawTests = obj({
  tests: list(
    obj({
      id: str,
      test_id: str,
      scenario: str,
      requirement: str,
      metric: str,
      value: num,
      ci95: ci,
      n: num,
      threshold: str,
      status: str,
      passed: bool,
      mlflow_run_id: str,
    }),
  ),
  error: str,
  runs: num,
  passed: num,
  failed: num,
});

export function toTestResults(data: unknown): TestResultsData {
  const d = parse(RawTests, data);
  return {
    tests: d.tests.map((t, i) => ({
      id: t.id ?? `${t.test_id ?? 'test'}-${i}`,
      testId: t.test_id,
      scenario: t.scenario,
      requirement: t.requirement,
      metric: t.metric,
      value: t.value ?? null,
      ci: t.ci95 ?? null,
      n: t.n,
      threshold: t.threshold,
      status: t.status,
      passed: t.passed ?? null,
      runId: t.mlflow_run_id,
    })),
    error: d.error,
    summary: d.runs != null ? { runs: d.runs, passed: d.passed, failed: d.failed } : undefined,
  };
}

// ---- findings ---------------------------------------------------------------------------

const RawEvidence = obj({
  // real
  test_id: str,
  metric: str,
  value: num,
  ci95: ci,
  threshold: str,
  threshold_source: str,
  mlflow_run_id: str,
  // mock
  text: str,
  ci,
  runId: str,
});

const RawFinding = obj({
  id: str,
  requirement: str,
  title: str,
  verdict: str,
  confidence: num,
  reasoning: str,
  evidence: list(RawEvidence),
  counter_evidence: strList,
  counterEvidence: strList,
  would_change_if: strList,
  wouldChangeIf: strList,
  citations: list(obj({ provision: str, provision_id: str, kbVersion: str, kb_version: str, quote: str })),
  limitations: strList,
  metric: obj({ name: str, value: num, ci, threshold: num, thresholdSource: str }),
  verdict_before_critic: str,
  critic: obj({
    originalVerdict: str,
    adjusted: bool,
    note: str,
    call: str,
    strongest_objection: str,
  }),
  kb_version: str,
});

function toFinding(raw: unknown): Finding | null {
  const f = parse(RawFinding, raw);
  if (!f.id) return null;
  const evidence = f.evidence.map((e) => {
    const value = e.value != null ? ` = ${e.value}` : '';
    const thr = e.threshold ? ` (threshold ${e.threshold})` : '';
    return {
      text: e.text ?? `${e.test_id ?? 'test'}: ${e.metric ?? 'metric'}${value}${thr}`,
      ci: first(e.ci, e.ci95),
      runId: first(e.runId, e.mlflow_run_id),
    };
  });
  const ev = f.evidence.find((e) => e.value != null || e.ci95);
  const hasMock = !!f.metric.name;
  const metric: Finding['metric'] = hasMock
    ? {
        name: f.metric.name!,
        value: f.metric.value ?? null,
        ci: f.metric.ci ?? null,
        threshold: f.metric.threshold,
        thresholdSource: f.metric.thresholdSource,
      }
    : ev
      ? {
          name: ev.metric ?? ev.test_id ?? 'metric',
          value: ev.value ?? null,
          ci: ev.ci95 ?? null,
          threshold: thresholdNumber(ev.threshold),
          thresholdText: ev.threshold,
          thresholdSource: ev.threshold_source,
        }
      : undefined;
  const hasCritic = !!(
    f.critic.call ||
    f.critic.note ||
    f.critic.strongest_objection ||
    f.verdict_before_critic
  );
  const original = first(f.critic.originalVerdict, f.verdict_before_critic);
  return {
    id: f.id,
    requirement: f.requirement,
    title: f.title,
    verdict: f.verdict ?? 'inconclusive',
    confidence: f.confidence ?? null,
    metric,
    evidence,
    counterEvidence: [...f.counterEvidence, ...f.counter_evidence],
    wouldChangeIf: [...f.wouldChangeIf, ...f.would_change_if],
    reasoning: f.reasoning,
    citations: f.citations
      .filter((c) => c.provision || c.provision_id)
      .map((c) => ({
        provision: (c.provision ?? c.provision_id)!,
        kbVersion: first(c.kbVersion, c.kb_version, f.kb_version),
        quote: c.quote,
      })),
    limitations: f.limitations,
    critic: hasCritic
      ? {
          originalVerdict: original,
          adjusted: f.critic.adjusted ?? (!!original && original !== f.verdict),
          note: first(f.critic.note, f.critic.strongest_objection),
          call: f.critic.call,
        }
      : undefined,
  };
}

/** One artifact's findings: the mock `{findings: [...]}` or one real finding per artifact. */
export function toFindings(data: unknown): FindingsData {
  const raw = asObj(data);
  const items = Array.isArray(raw.findings) ? raw.findings : [raw];
  return { findings: items.map(toFinding).filter((f): f is Finding => f !== null) };
}

/** All live findings of an audit, merged across finding artifacts, sorted by id. */
export function findingsFromArtifacts(artifacts: Artifact[]): Finding[] {
  const byId = new Map<string, { f: Finding; v: number }>();
  for (const a of artifacts) {
    if (a.kind !== 'finding' || a.status === 'superseded') continue;
    for (const f of toFindings(a.data).findings) {
      const prev = byId.get(f.id);
      if (!prev || a.version >= prev.v) byId.set(f.id, { f, v: a.version });
    }
  }
  return [...byId.values()].map((x) => x.f).sort((x, y) => x.id.localeCompare(y.id));
}

// ---- critic ----------------------------------------------------------------------------

const RawCritic = obj({
  reviews: list(
    obj({
      findingId: str,
      finding_id: str,
      challenge: str,
      strongest_objection: str,
      attempt: str,
      checked_evidence: strList,
      outcome: str,
      call: str,
      newVerdict: str,
      adjusted_verdict: str,
      confidenceDelta: num,
      adjusted_confidence: num,
    }),
  ),
  summary: str,
  overall: str,
});

export function toCritic(data: unknown): CriticData {
  const d = parse(RawCritic, data);
  return {
    reviews: d.reviews
      .filter((r) => r.findingId || r.finding_id)
      .map((r) => ({
        findingId: (r.findingId ?? r.finding_id)!,
        challenge: first(r.challenge, r.strongest_objection),
        attempt: first(
          r.attempt,
          r.checked_evidence.length ? `Checked: ${r.checked_evidence.join(', ')}` : undefined,
        ),
        outcome: first(r.outcome, r.call) ?? 'upheld',
        newVerdict: first(r.newVerdict, r.adjusted_verdict),
        confidenceDelta: r.confidenceDelta ?? null,
        newConfidence: r.adjusted_confidence ?? null,
      })),
    summary: first(d.summary, d.overall),
  };
}

// ---- report --------------------------------------------------------------------------------

const RawReport = obj({
  audience: str,
  title: str,
  markdown: str,
  traffic: list(obj({ requirement: str, title: str, light: str, note: str })),
  reproducibility: z.unknown(),
  engineer_markdown: str,
  management: obj({
    headline: str,
    traffic_lights: list(obj({ requirement: str, status: str, note: str })),
    decisions_needed: strList,
    next_steps: strList,
  }),
});

function toReproducibility(v: unknown): ReportData['reproducibility'] {
  if (!isObj(v)) return undefined;
  const r = parse(obj({ kbVersion: str, cardVersion: num, seeds: list(num), mlflowRuns: strList }), v);
  return {
    kbVersion: r.kbVersion ?? '–',
    cardVersion: r.cardVersion ?? 0,
    seeds: r.seeds.filter((s): s is number => s != null),
    mlflowRuns: r.mlflowRuns,
  };
}

/**
 * The report views of one report artifact. The pipeline writes one `main` artifact holding
 * both the engineer markdown and the management summary; the mocks write `engineer` and
 * `management` artifacts. A lone `main` report with plain markdown renders as engineer.
 */
export function toReports(data: unknown, name = 'main'): ReportData[] {
  const d = parse(RawReport, data);
  const out: ReportData[] = [];
  const m = d.management;
  if (d.markdown != null || d.traffic.length) {
    const audience = d.audience === 'management' || name === 'management' ? 'management' : 'engineer';
    out.push({
      audience,
      title: d.title,
      markdown: d.markdown ?? '',
      traffic: d.traffic.length
        ? d.traffic
            .filter((t) => t.requirement)
            .map((t) => ({
              requirement: t.requirement!,
              title: t.title,
              light: t.light ?? 'grey',
              note: t.note,
            }))
        : undefined,
      reproducibility: toReproducibility(d.reproducibility),
    });
  }
  if (d.engineer_markdown != null) {
    out.push({ audience: 'engineer', title: 'Engineer report', markdown: d.engineer_markdown });
  }
  if (m.headline || m.traffic_lights.length || m.decisions_needed.length || m.next_steps.length) {
    out.push({
      audience: 'management',
      title: m.headline,
      markdown: '',
      traffic: m.traffic_lights
        .filter((t) => t.requirement)
        .map((t) => ({ requirement: t.requirement!, light: t.status ?? 'grey', note: t.note })),
      decisions: m.decisions_needed,
      nextSteps: m.next_steps,
    });
  }
  return out;
}

/** Report views across report artifacts, engineer first. */
export function reportsFromArtifacts(
  artifacts: Artifact[],
): { key: string; artifact: Artifact; report: ReportData }[] {
  const out = artifacts
    .filter((a) => a.kind === 'report')
    .flatMap((a) =>
      toReports(a.data, a.name).map((report) => ({ key: `${a.id}-${report.audience}`, artifact: a, report })),
    );
  return out.sort((x, y) =>
    x.report.audience === y.report.audience ? 0 : x.report.audience === 'engineer' ? -1 : 1,
  );
}

// ---- audit-level facts ---------------------------------------------------------------------

/** The audit's kb_version: audit.data (mocks) or the artifacts' stamp (real pipeline). */
export function auditKbVersion(audit: {
  data: Record<string, unknown>;
  artifacts?: Artifact[];
}): string | undefined {
  const fromData = parse(str, audit.data.kbVersion ?? audit.data.kb_version);
  if (fromData) return fromData;
  for (const a of audit.artifacts ?? []) {
    const v = parse(str, asObj(a.data).kb_version);
    if (v) return v;
  }
  return undefined;
}

/** The system card version the audit ran against (context artifact), if known. */
export function auditCardVersion(audit: {
  data: Record<string, unknown>;
  artifacts?: Artifact[];
}): number | undefined {
  const fromData = parse(num, audit.data.cardVersion ?? audit.data.card_version);
  if (fromData != null) return fromData;
  const ctx = (audit.artifacts ?? []).find((a) => a.kind === 'context');
  return ctx ? parse(num, asObj(asObj(ctx.data).system).card_version) : undefined;
}

// ---- per-step facts (the run page's step panel) -----------------------------------------------

/** Memory a step's artifacts cite (memory_applied) and write (lessons_recorded). */
export function stepMemory(artifacts: Artifact[]): { applied: string[]; recorded: string[] } {
  const applied = new Set<string>();
  const recorded = new Set<string>();
  for (const a of artifacts) {
    const d = asObj(a.data);
    for (const l of parse(strList, d.lessons_recorded)) recorded.add(l);
    for (const sc of Array.isArray(d.scenarios) ? d.scenarios : []) {
      for (const m of parse(strList, asObj(sc).memory_applied)) applied.add(m);
      for (const m of parse(strList, asObj(sc).memoryApplied)) applied.add(m);
    }
    for (const m of parse(strList, d.memory_applied)) applied.add(m);
  }
  return { applied: [...applied], recorded: [...recorded] };
}

/** Every version of the given kinds (superseded ones too), oldest first: the redo history. */
export function artifactVersions(artifacts: Artifact[], kinds: readonly string[]): Artifact[] {
  return artifacts
    .filter((a) => kinds.includes(a.kind))
    .sort((x, y) => x.kind.localeCompare(y.kind) || x.name.localeCompare(y.name) || x.version - y.version);
}

export interface SearchDriver {
  id: string;
  title?: string;
  fields: string[];
}

/**
 * The scenarios that drove the public dataset search. Uses the candidates artifact's own list
 * when it has one (`scenarios` / `scenario_ids` / `driven_by`); otherwise derives it from the
 * scenario plan: scenarios whose data needs touch the fields the search looked for.
 */
export function searchDrivers(
  candidates: unknown,
  scenarios: unknown,
): { explicit: boolean; drivers: SearchDriver[] } {
  const c = asObj(candidates);
  const plan = parse(
    obj({
      scenarios: list(
        obj({
          id: str,
          expected_behaviour: str,
          title: str,
          protected: strList,
          proxies: strList,
          data_needs: obj({ fields: strList }),
        }),
      ),
    }),
    scenarios,
  ).scenarios.filter((s) => s.id);
  const toDriver = (s: (typeof plan)[number]): SearchDriver => ({
    id: s.id!,
    title: first(s.title, s.expected_behaviour),
    fields: [...new Set([...s.data_needs.fields, ...s.protected, ...s.proxies])],
  });
  const listed = [c.scenarios, c.scenario_ids, c.driven_by].find(Array.isArray) as unknown[] | undefined;
  if (listed) {
    const ids = listed
      .map((x) => (isObj(x) ? parse(str, x.id) : parse(str, x)))
      .filter((x): x is string => !!x);
    return {
      explicit: true,
      drivers: ids.map((id) => {
        const s = plan.find((p) => p.id === id);
        return s ? toDriver(s) : { id, fields: [] };
      }),
    };
  }
  const wanted = new Set([...parse(strList, c.protected), ...Object.keys(asObj(c.mapping))]);
  const drivers = plan.map(toDriver).filter((d) => !wanted.size || d.fields.some((f) => wanted.has(f)));
  return { explicit: false, drivers };
}
