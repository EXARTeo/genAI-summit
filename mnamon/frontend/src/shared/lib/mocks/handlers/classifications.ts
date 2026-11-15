// Mock of the risk-classification API (plan 02 §7.3): runs, approve / reject, stale, and the
// obligations preview. Fixtures: SYS-001 approved then stale, SYS-002 a needs_human proposal,
// SYS-003 never classified; a newly registered CV Parser gets the Art. 6(3)(a) proposal.
import { parse, stringify } from 'yaml';
import type { ClassificationResult } from '@/features/classification/lib/types';
import type { SystemCard } from '@/features/systems/lib/types';
import { mockSystems, writeFile } from '../fixtures/systems';
import { mockTime } from '../time';
import { MockResponse, mockError, type MockRoute } from '../types';

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => !!v && typeof v === 'object' && !Array.isArray(v);

interface Event {
  id: number;
  classification_id: string;
  system_id: string;
  action: string;
  actor: string;
  reason: string | null;
  data: Obj;
  at: string;
}

interface Row {
  id: string;
  system_id: string;
  status: string;
  kb_version: string | null;
  dossier_version: Record<string, number>;
  input: Obj;
  result: ClassificationResult | null;
  error: string | null;
  trace_id: string | null;
  previous_id: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  events: Event[];
}

const KB = '2026.11.15-1';
const RUN_MS = import.meta.env.MODE === 'test' ? 0 : 9_000;
const rows = new Map<string, Row[]>(); // system id -> runs, oldest first
let seq = 1;

const cite = (id: string, quote: string, extra: Partial<ClassificationResult['citations'][number]> = {}) => ({
  id,
  kb_version: KB,
  quote,
  binding: !id.startsWith('INT.'),
  status: 'final',
  ...extra,
});

const KEY_DATES_HIGH = [
  { what: 'Prohibited practices apply', date: '2025-02-02', provision_id: 'AIA.5', amended_by: null },
  {
    what: 'High-risk duties apply (Annex III)',
    date: '2027-12-02',
    provision_id: 'AIA.6.2',
    amended_by: 'OMNIBUS.1.12',
  },
];

const BASE = {
  art5_screening: [
    { provision_id: 'AIA.5.1.f', applies: false, why: 'No emotion recognition of workers or candidates.' },
  ],
  transparency: { features: [], provisions: [] },
  gpai: { is_gpai_model: false, built_on_gpai: false, note: null },
  prechecks: {},
  decided_by: 'gemini+iris',
  verifier_problems: [],
};

/** A CV parser that only structures CVs: Annex III 4(a) considered, Art. 6(3)(a) holds. */
function parserResult(): ClassificationResult {
  return {
    ...BASE,
    risk_class: 'minimal_risk',
    route: 'art6_3_exempt',
    annex_basis: null,
    annex_basis_id: null,
    role: 'provider',
    role_reasoning: 'Built in-house and placed into service under the organisation’s own name (Art. 3(3)).',
    annex_iii_considered: [
      {
        provision_id: 'AIA.ANNEX_III.4.a',
        applies: true,
        why: 'Used in recruitment: it processes job applications, so the area is in scope before Art. 6(3).',
      },
    ],
    art6_3: {
      considered: true,
      condition: 'a',
      profiling: 'no',
      holds: true,
      why: 'It only converts CVs into structured fields; it does not score, rank or filter (spec §3), and recruiters check every field. The draft guideline’s Example 12 treats such a parser as a narrow procedural task.',
    },
    reasoning:
      'The system is used in recruitment (Annex III point 4(a)), but it performs a narrow procedural task: turning unstructured CVs into structured records without assessing the candidates. It does not profile people. Art. 6(3)(a) therefore applies and the system is not high risk, provided the Art. 6(4) assessment is documented before it is placed on the market and it is registered under Art. 49(2).',
    counter_arguments: [
      {
        argument:
          'If the parser’s output order or field completeness is used to filter or shortlist candidates, it materially influences the recruitment decision and 4(a) applies in full.',
        would_change_to: 'high_risk',
      },
    ],
    would_change_if: [
      'It scores, ranks or filters candidates, or recruiters sort by an extracted field it infers.',
      'It infers personal traits (fit, personality, reliability) from the CV.',
    ],
    uncertainties: [
      {
        question: 'Do recruiters sort or filter the candidate list by any extracted field?',
        why_it_matters: 'Sorting by an inferred field could turn the procedural task into a filtering one.',
        ask: 'PM',
      },
    ],
    next_steps: [
      'Document the Art. 6(4) assessment before placing on the market.',
      'Register the system in the EU database under Art. 49(2).',
    ],
    confidence: 0.81,
    citations: [
      cite(
        'AIA.ANNEX_III.4.a',
        'AI systems intended to be used for the recruitment or selection of natural persons…',
      ),
      cite('AIA.6.3', 'the AI system is intended to perform a narrow procedural task'),
      cite(
        'AIA.6.4',
        'A provider who considers that an AI system referred to in Annex III is not high-risk shall document its assessment',
      ),
      cite(
        'INT.demo-art6-guideline-mirror.example-12',
        'A CV parser that only extracts and structures information … performs a narrow procedural task.',
        {
          binding: false,
          status: 'draft',
        },
      ),
    ],
    kb_version: KB,
    key_dates: [
      { what: 'Prohibited practices apply', date: '2025-02-02', provision_id: 'AIA.5', amended_by: null },
      {
        what: 'Art. 6(4) documentation and Art. 49(2) registration',
        date: '2027-12-02',
        provision_id: 'AIA.6.4',
        amended_by: 'OMNIBUS.1.12',
      },
    ],
    iris: {
      choice: 'not_high_risk_6_3',
      probabilities: { not_high_risk_6_3: 0.74, high_risk_annex_iii: 0.21, minimal: 0.05 },
      confidence: 0.74,
      profiling: 0.12,
    },
    agreement: true,
    needs_human: false,
    needs_human_reasons: [],
    trace_id: null,
  } as ClassificationResult;
}

function highRiskResult(point: '4.a' | '5.b', opts: { needsHuman?: boolean } = {}): ClassificationResult {
  const recruit = point === '4.a';
  const annexId = `AIA.ANNEX_III.${point}`;
  return {
    ...BASE,
    risk_class: 'high_risk',
    route: 'art6_2_annex_iii',
    annex_basis: recruit ? 'Annex III 4(a)' : 'Annex III 5(b)',
    annex_basis_id: annexId,
    role: 'provider',
    role_reasoning: 'Developed in-house and put into service under the organisation’s name (Art. 3(3)).',
    annex_iii_considered: [
      {
        provision_id: annexId,
        applies: true,
        why: recruit
          ? 'It ranks and filters candidates for recruiters: recruitment and selection of natural persons.'
          : 'It evaluates the creditworthiness of natural persons.',
      },
    ],
    art6_3: {
      considered: true,
      condition: null,
      profiling: 'yes',
      holds: false,
      why: 'It evaluates personal aspects of people (profiling), so the derogation can never apply.',
    },
    reasoning: recruit
      ? 'The system ranks applicants and recruiters shortlist from its ranking. That is recruitment and selection under Annex III point 4(a). It profiles candidates, so Art. 6(3) is excluded. The organisation built it, so it is the provider.'
      : 'The system scores applicants’ creditworthiness, an Annex III point 5(b) use. Scoring people is profiling, so Art. 6(3) cannot apply. Fraud-detection use would be excepted, but the dossier describes consumer lending.',
    counter_arguments: [
      {
        argument: recruit
          ? 'If recruiters never see the ranking and it only sorts by arrival time, it could be a procedural task.'
          : 'If the score is used only to detect fraud, point 5(b) excepts it.',
        would_change_to: 'minimal_risk',
      },
    ],
    would_change_if: [
      recruit
        ? 'The ranking is removed from the recruiter view.'
        : 'The score is used only for fraud detection.',
    ],
    uncertainties: opts.needsHuman
      ? [
          {
            question: 'Is the score used for consumer lending decisions or only for internal fraud checks?',
            why_it_matters: 'Fraud detection is excepted from point 5(b).',
            ask: 'PM',
          },
        ]
      : [],
    next_steps: ['Plan the provider obligations (Art. 9-15, 17, 43, 49(1)) before 2027-12-02.'],
    confidence: opts.needsHuman ? 0.58 : 0.9,
    citations: [
      cite(
        annexId,
        recruit
          ? 'AI systems intended to be used for the recruitment or selection of natural persons…'
          : 'AI systems intended to be used to evaluate the creditworthiness of natural persons…',
      ),
      cite('AIA.6.2', 'AI systems referred to in Annex III shall be considered to be high-risk.'),
      cite(
        'AIA.6.3',
        'an AI system referred to in Annex III shall always be considered to be high-risk where the AI system performs profiling',
      ),
      cite('INT.draft-guidelines-high-risk-annex-iii.4', 'Examples of use cases under point 4…', {
        binding: false,
        status: 'draft',
      }),
    ],
    kb_version: KB,
    key_dates: KEY_DATES_HIGH,
    iris: opts.needsHuman
      ? {
          choice: 'high_risk_annex_iii',
          probabilities: { high_risk_annex_iii: 0.52, minimal: 0.31, not_high_risk_6_3: 0.17 },
          confidence: 0.52,
          profiling: 0.81,
        }
      : {
          choice: 'high_risk_annex_iii',
          probabilities: { high_risk_annex_iii: 0.88, not_high_risk_6_3: 0.09, minimal: 0.03 },
          confidence: 0.88,
          profiling: 0.9,
        },
    agreement: true,
    needs_human: !!opts.needsHuman,
    needs_human_reasons: opts.needsHuman
      ? ['Classifier confidence 58% is below 60%.', 'Iris confidence 52% is below 60%.']
      : [],
    trace_id: null,
  } as ClassificationResult;
}

function genericResult(): ClassificationResult {
  return {
    ...BASE,
    risk_class: 'minimal_risk',
    route: 'none',
    annex_basis: null,
    annex_basis_id: null,
    role: 'provider',
    role_reasoning: 'Developed in-house (Art. 3(3)).',
    annex_iii_considered: [],
    art6_3: { considered: false, condition: null, profiling: 'unknown', holds: null, why: '' },
    reasoning:
      'No Annex I product, no Annex III area and no Art. 5 practice matches the dossier; no Art. 50 feature is declared.',
    counter_arguments: [
      {
        argument: 'The dossier is short: an unlisted use could fall under Annex III.',
        would_change_to: 'high_risk',
      },
    ],
    would_change_if: ['It is used in an Annex III area (employment, credit, essential services, ...).'],
    uncertainties: [
      {
        question: 'Which decisions use its output?',
        why_it_matters: 'Annex III depends on the use.',
        ask: 'PM',
      },
    ],
    next_steps: ['Keep the AI literacy measures (Art. 4) in place.'],
    confidence: 0.55,
    citations: [cite('AIA.6.2', 'AI systems referred to in Annex III shall be considered to be high-risk.')],
    kb_version: KB,
    key_dates: [],
    iris: null,
    agreement: null,
    needs_human: true,
    needs_human_reasons: ['Independent check unavailable.', 'Classifier confidence 55% is below 60%.'],
    trace_id: null,
  } as ClassificationResult;
}

function addEvent(
  row: Row,
  action: string,
  actor: string,
  reason: string | null = null,
  data: Obj = {},
  at = new Date().toISOString(),
) {
  row.events.push({
    id: seq++,
    classification_id: row.id,
    system_id: row.system_id,
    action,
    actor,
    reason,
    data,
    at,
  });
  row.updated_at = at;
}

function newId(systemId: string, at: Date): string {
  const d = at.toISOString();
  const base = `CLS-${systemId}-${d.slice(0, 10).replace(/-/g, '')}-${d.slice(11, 16).replace(':', '')}`;
  const taken = new Set((rows.get(systemId) ?? []).map((r) => r.id));
  if (!taken.has(base)) return base;
  let n = 2;
  while (taken.has(`${base}-${n}`)) n++;
  return `${base}-${n}`;
}

function makeRow(systemId: string, at: string, previousId: string | null = null): Row {
  const row: Row = {
    id: newId(systemId, new Date(at)),
    system_id: systemId,
    status: 'running',
    kb_version: KB,
    dossier_version: { 'system-card.yaml': 1 },
    input: {},
    result: null,
    error: null,
    trace_id: null,
    previous_id: previousId,
    created_by: 'client:demo',
    created_at: at,
    updated_at: at,
    events: [],
  };
  addEvent(row, 'created', 'client:demo', null, {}, at);
  rows.set(systemId, [...(rows.get(systemId) ?? []), row]);
  return row;
}

function propose(row: Row, result: ClassificationResult, at?: string) {
  row.result = { ...result, trace_id: `trace-${row.id.toLowerCase()}` };
  row.trace_id = row.result.trace_id ?? null;
  row.status = 'proposed';
  addEvent(row, 'proposed', 'agent:classifier', null, {}, at);
}

// ---- fixtures ---------------------------------------------------------------------------
{
  const r1 = makeRow('SYS-001', mockTime('2026-11-13T09:10:00Z'));
  propose(r1, highRiskResult('4.a'), mockTime('2026-11-13T09:11:00Z'));
  r1.status = 'approved';
  addEvent(r1, 'approved', 'client:demo', null, {}, mockTime('2026-11-13T09:30:00Z'));
  r1.status = 'stale';
  addEvent(
    r1,
    'stale',
    'system',
    null,
    { change_id: 'RC-2026.11.15-1', provisions: ['AIA.6.3'] },
    mockTime('2026-11-14T17:40:00Z'),
  );

  const r2 = makeRow('SYS-002', mockTime('2026-11-14T16:00:00Z'));
  propose(r2, highRiskResult('5.b', { needsHuman: true }), mockTime('2026-11-14T16:01:00Z'));
}

// ---- behaviour ----------------------------------------------------------------------------

function cardOf(systemId: string): Obj {
  const f = mockSystems.read(systemId, 'system-card.yaml');
  try {
    const c: unknown = f ? parse(f.text) : null;
    if (isObj(c)) return c;
  } catch {
    /* fall through */
  }
  const s = mockSystems.get(systemId);
  return isObj(s?.data.card) ? (s.data.card as Obj) : ((s?.data ?? {}) as Obj);
}

/** Pick the fixture the run "finds", from the card text and the rejection feedback. */
function decideFor(row: Row): ClassificationResult {
  const text = JSON.stringify(cardOf(row.system_id)).toLowerCase();
  const prev = row.previous_id ? findRow(row.system_id, row.previous_id) : undefined;
  const feedback = prev?.events.find((e) => e.action === 'rejected')?.reason;
  const cv = /\b(cv|cvs|candidate|recruit\w*|applicant)\b/.test(text);
  if (/credit/.test(text)) return highRiskResult('5.b', { needsHuman: true });
  if (cv && (feedback || !/does not (score|rank)/.test(text))) return highRiskResult('4.a');
  if (cv) return parserResult();
  return genericResult();
}

function findRow(systemId: string, id: string): Row | undefined {
  return (rows.get(systemId) ?? []).find((r) => r.id === id);
}

/** Finish runs whose time is up (the real one is a background task). */
function settle(systemId: string) {
  for (const r of rows.get(systemId) ?? []) {
    if (r.status === 'running' && Date.now() - Date.parse(r.created_at) >= RUN_MS) propose(r, decideFor(r));
  }
}

const list = (systemId: string) => {
  settle(systemId);
  return [...(rows.get(systemId) ?? [])].reverse();
};

function approve(systemId: string, row: Row, reason: string | null) {
  for (const r of rows.get(systemId) ?? []) {
    if (r !== row && (r.status === 'approved' || r.status === 'stale')) {
      r.status = 'superseded';
      addEvent(r, 'superseded', 'client:demo', `superseded by ${row.id}`);
    }
  }
  row.status = 'approved';
  addEvent(row, 'approved', 'client:demo', reason);
  const res = row.result!;
  const at = new Date().toISOString();
  const keys: Obj = {
    risk_class: res.risk_class,
    annex_basis: res.annex_basis ?? null,
    role: res.role,
    features: res.transparency?.features ?? [],
    ...(res.art6_3?.holds
      ? { art_6_3_claim: { claimed: true, condition: res.art6_3.condition, assessed_in: row.id } }
      : {}),
    classification: { id: row.id, kb_version: row.kb_version, approved_by: 'client:demo', approved_at: at },
    provenance: 'classified_by_agent_approved_by_human',
  };
  const card = { ...cardOf(systemId), ...keys };
  writeFile(
    systemId,
    'system-card.yaml',
    stringify(card),
    'client:demo',
    `classification ${row.id} approved`,
  );
  writeFile(
    systemId,
    'classification.yaml',
    stringify({ id: row.id, ...res }),
    'client:demo',
    `classification ${row.id} approved`,
  );
  const sys = mockSystems.get(systemId);
  const data = isObj(sys?.data.card)
    ? { card: { ...(sys!.data.card as Obj), ...keys } }
    : (keys as Partial<SystemCard>);
  mockSystems.update(systemId, { status: 'active', data: data as Partial<SystemCard> });
}

// ---- obligations preview ------------------------------------------------------------------

const HIGH_ROWS: [string, string, string][] = [
  ['OBL.AIA.9.risk-management', 'AIA.9', 'Establish and maintain a risk management system.'],
  [
    'OBL.AIA.10.data-governance',
    'AIA.10',
    'Data governance for training, validation and test data, incl. bias examination.',
  ],
  ['OBL.AIA.11.technical-documentation', 'AIA.11', 'Draw up the technical documentation (Annex IV).'],
  ['OBL.AIA.12.record-keeping', 'AIA.12', 'Automatic logging of events over the lifetime.'],
  ['OBL.AIA.13.transparency-to-deployers', 'AIA.13', 'Instructions for use for deployers.'],
  ['OBL.AIA.14.human-oversight', 'AIA.14', 'Design for effective human oversight.'],
  ['OBL.AIA.15.accuracy-robustness', 'AIA.15', 'Accuracy, robustness and cybersecurity.'],
  ['OBL.AIA.43.conformity-assessment', 'AIA.43', 'Conformity assessment before placing on the market.'],
  ['OBL.AIA.49.1.registration', 'AIA.49.1', 'Register in the EU database (high-risk).'],
];

function preview(systemId: string) {
  const runs = list(systemId);
  const cur = runs.find((r) => r.status === 'approved' || r.status === 'stale');
  if (!cur?.result) return mockError(404, 'No approved classification');
  const res = cur.result;
  const high = res.risk_class === 'high_risk';
  const exempt = !!res.art6_3?.holds;
  const today = new Date().toISOString().slice(0, 10);
  const row = (
    id: string,
    article: string,
    summary: string,
    applicable: boolean,
    reason: string,
    date: string,
  ) => ({
    id,
    article,
    summary,
    applicable,
    reason,
    in_force_date: date,
    in_force_now: date <= today,
  });
  const items = [
    row(
      'OBL.AIA.4.ai-literacy',
      'AIA.4',
      'Ensure a sufficient level of AI literacy of staff.',
      true,
      'applies to every operator',
      '2025-02-02',
    ),
    row(
      'OBL.AIA.5.prohibited-practices-screening',
      'AIA.5.1',
      'Screen the system against the prohibited practices.',
      true,
      'applies to every operator',
      '2025-02-02',
    ),
    ...HIGH_ROWS.map(([id, art, s]) =>
      row(
        id,
        art,
        s,
        high,
        high ? `high-risk ${res.annex_basis ?? ''}`.trim() : 'not high-risk',
        '2027-12-02',
      ),
    ),
    row(
      'OBL.AIA.6.4.non-high-risk-assessment',
      'AIA.6.4',
      'Document the assessment that the Annex III system is not high-risk.',
      exempt,
      exempt ? 'Art. 6(3) derogation claimed' : 'no 6(3) claim',
      '2027-12-02',
    ),
    row(
      'OBL.AIA.49.2.registration-non-high-risk',
      'AIA.49.2',
      'Register the system although it is not high-risk.',
      exempt,
      exempt ? 'Art. 6(3) derogation claimed' : 'no 6(3) claim',
      '2027-12-02',
    ),
  ];
  return {
    systemId,
    classificationId: cur.id,
    classificationStatus: cur.status,
    classified: true,
    kb_version: cur.kb_version,
    prohibited: res.risk_class === 'prohibited',
    query: { role: res.role, risk_class: high ? 'high' : res.risk_class, exempt_6_3: exempt },
    total: items.length,
    items,
  };
}

const exists = (id: string) => !!mockSystems.get(id);

/** The backend's ClassificationOut is camelCase (the result stays snake_case). */
const out = (r: Row) => ({
  id: r.id,
  systemId: r.system_id,
  status: r.status,
  kbVersion: r.kb_version,
  dossierVersion: r.dossier_version,
  input: r.input,
  result: r.result,
  error: r.error,
  traceId: r.trace_id,
  previousId: r.previous_id,
  createdBy: r.created_by,
  createdAt: r.created_at,
  updatedAt: r.updated_at,
  events: r.events.map((e) => ({
    id: String(e.id),
    classificationId: e.classification_id,
    systemId: e.system_id,
    action: e.action,
    actor: e.actor,
    reason: e.reason,
    data: e.data,
    at: e.at,
  })),
});

export const routes: MockRoute[] = [
  {
    method: 'GET',
    path: '/v1/systems/:systemId/classifications',
    handler: ({ params }) =>
      exists(params.systemId) ? list(params.systemId).map(out) : mockError(404, 'System not found'),
  },
  {
    method: 'POST',
    path: '/v1/systems/:systemId/classifications',
    handler: ({ params, body }) => {
      const id = params.systemId;
      if (!exists(id)) return mockError(404, 'System not found');
      if (list(id).some((r) => r.status === 'running'))
        return mockError(409, 'A classification is already running');
      const previousId = isObj(body) && typeof body.previousId === 'string' ? body.previousId : null;
      return new MockResponse(202, out(makeRow(id, new Date().toISOString(), previousId)));
    },
  },
  {
    method: 'GET',
    path: '/v1/systems/:systemId/classifications/:cid',
    handler: ({ params }) => {
      settle(params.systemId);
      const row = findRow(params.systemId, params.cid);
      return row ? out(row) : mockError(404, 'Classification not found');
    },
  },
  {
    method: 'POST',
    path: '/v1/systems/:systemId/classifications/:cid/decision',
    handler: ({ params, body }) => {
      const row = findRow(params.systemId, params.cid);
      if (!row) return mockError(404, 'Classification not found');
      if (row.status !== 'proposed')
        return mockError(409, `Only a proposed classification can be decided (is ${row.status})`);
      const b = (isObj(body) ? body : {}) as { decision?: string; reason?: string };
      const reason = b.reason?.trim() || null;
      if (b.decision === 'reject') {
        if (!reason) return mockError(422, 'reason: required to reject');
        row.status = 'rejected';
        addEvent(row, 'rejected', 'client:demo', reason);
        return out(row);
      }
      if (b.decision !== 'approve') return mockError(422, 'decision: approve or reject');
      approve(params.systemId, row, reason);
      return out(row);
    },
  },
  {
    method: 'GET',
    path: '/v1/systems/:systemId/obligations',
    handler: ({ params }) =>
      exists(params.systemId) ? preview(params.systemId) : mockError(404, 'System not found'),
  },
];
