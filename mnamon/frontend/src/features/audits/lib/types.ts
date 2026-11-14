// Audit workflow types. Mirrors mnamon/backend/schema/audits.py (camelCase out),
// with typed views over the free-form `data` JSONB of each artifact kind.

export type ArtifactKind =
  | 'context'
  | 'model_profile'
  | 'public_dataset_candidates'
  | 'scenarios'
  | 'scenario_analysis'
  | 'generation_spec'
  | 'dataset'
  | 'dataset_analysis'
  | 'test_plan'
  | 'test_result'
  | 'finding'
  | 'critic'
  | 'report';

export type ArtifactStatus = 'proposed' | 'approved' | 'rejected' | 'changes_requested' | 'superseded';
export type Decision = 'approved' | 'rejected' | 'changes_requested';
export type ReasonCategory =
  | 'wrong_fact'
  | 'wrong_interpretation'
  | 'missing_info'
  | 'wrong_metric'
  | 'unrealistic_data'
  | 'org_policy'
  | 'other';

/** open | running | waiting_approval | done | failed (backend keeps it free-form). */
export type AuditStatus = 'open' | 'running' | 'waiting_approval' | 'done' | 'failed' | (string & {});

export interface Artifact<D = Record<string, unknown>> {
  id: string;
  auditId: string;
  kind: ArtifactKind | (string & {});
  name: string;
  version: number;
  status: ArtifactStatus | (string & {});
  data: D;
  fileRefs: unknown[];
  parentId: string | null;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
}

export interface Approval {
  id: string;
  auditId: string;
  artifactId: string | null;
  gate: string;
  decision: Decision | (string & {});
  reasonCategory: ReasonCategory | null;
  comment: string | null;
  edits: Record<string, unknown>;
  decidedBy: string;
  at: string;
}

export interface AuditData {
  systemName?: string;
  title?: string;
  kbVersion?: string;
  cardVersion?: number;
  traceId?: string;
  /** Per-stage trace (span) ids, keyed by stage id. */
  stageTraces?: Record<string, string>;
  /** Per-stage timings in seconds. */
  stageDurations?: Record<string, number>;
  trigger?: string;
  summary?: { gaps?: number; supports?: number; inconclusive?: number; notAssessable?: number };
  [k: string]: unknown;
}

export interface Audit {
  id: string;
  systemId: string;
  status: AuditStatus;
  stage: string;
  createdBy: string | null;
  data: AuditData;
  createdAt: string;
  updatedAt: string;
}

export interface AuditDetail extends Audit {
  artifacts: Artifact[];
  approvals: Approval[];
}

export interface ApprovalIn {
  gate: string;
  decision: Decision;
  artifactId?: string | null;
  reasonCategory?: ReasonCategory | null;
  comment?: string | null;
  edits?: Record<string, unknown>;
}

export interface ApprovalResult {
  approval: Approval;
  artifact: Artifact | null;
}

// ---- artifact view models -----------------------------------------------------
// What the views render. The pipeline writes snake_case shapes (mnamon/agents/pipeline);
// `adapters.ts` maps every artifact (real or mock) onto these, so a missing field is
// `undefined` / `null` / `[]` here and the views render "–" instead of crashing.

export interface Citation {
  provision: string; // e.g. "AI Act Art. 10(2)(f)" or "AIA.10.2.f"
  kbVersion?: string;
  quote?: string;
}

export interface ContextData {
  system: {
    id?: string;
    name?: string;
    annex?: string;
    role?: string;
    intendedPurpose?: string;
    riskClass?: string;
  };
  requirements: { id: string; title?: string; provision?: string; testable: boolean }[];
  plugins: { name: string; accessType?: string; placement?: string }[];
  filesRead: { path: string; version?: number }[];
  kbVersion?: string;
  target?: string;
}

export interface ModelProfileData {
  model: { name?: string; version?: string; flavor?: string; metrics: Record<string, number> };
  sensitivity: { feature: string; score: number; protectedProxy?: boolean; note?: string }[];
  boundary: { feature: string; threshold?: string; flipRate: number | null; note?: string }[];
  probes?: number;
  notes: string[];
}

export interface Scenario {
  id: string;
  title?: string;
  template?: string;
  requirement?: string;
  groups: string[];
  n?: number;
  priority?: 'high' | 'medium' | 'low';
  rationale?: string;
  metric?: string;
  /** Memory entry paths this scenario follows ("learned from memory"). */
  memoryApplied?: string[];
}

export interface ScenariosData {
  scenarios: Scenario[];
  notTestable?: string[];
  assumptions?: string[];
}

export interface ScenarioAnalysisData {
  coverage: { requirement: string; scenarios: string[]; status: 'covered' | 'partial' | 'not_testable' }[];
  risks: string[];
  notTestable: { requirement: string; why?: string }[];
  diff?: { added: string[]; removed: string[]; changed: string[] };
  summary?: string;
  /** Protected attributes, proxies and monotone fields the plan covers. */
  attributeCoverage?: { name: string; kind: string; covered: boolean }[];
}

export type Provenance =
  | 'dictionary'
  | 'training_doc'
  | 'business_rule'
  | 'llm_assumption'
  | 'memory'
  | 'public_data';

export interface GenerationSpecData {
  testSpec?: string;
  yaml: string;
  mode?: string;
  assumptions: { field: string; what?: string; provenance: Provenance | (string & {}) }[];
  diff?: { field: string; before: string; after: string; provenance: Provenance }[];
  problems?: string[];
  rationale?: string;
}

export type GateStatus = 'pass' | 'warn' | 'fail';
export type GateName = 'schema' | 'business_rules' | 'realism' | 'coverage' | 'privacy';

export interface GateResult {
  status: GateStatus;
  metrics?: Record<string, number | string | boolean>;
  note?: string;
}

export interface TwinPair {
  pairId: string;
  mode: string;
  changed: string[];
  base: Record<string, string | number>;
  twin: Record<string, string | number>;
  scoreBase: number;
  scoreTwin: number;
}

export interface TwinModeSummary {
  mode: string;
  label: string;
  description?: string;
  flipRate: number | null;
  meanDelta: number | null;
  ci: [number, number] | null;
  pairs?: number;
  validShare?: number | null;
}

export interface DatasetAnalysisData {
  datasetId?: string;
  name?: string;
  rows?: number;
  pairs?: number;
  gates: Partial<Record<GateName, GateResult>>;
  coverage: { rows: string[]; cols: string[]; counts: number[][]; minPerCell: number; label?: string };
  twinModes: TwinModeSummary[];
  twins: TwinPair[];
  limitations: string[];
}

export type Verdict = 'supports_compliance' | 'indicates_gap' | 'inconclusive' | 'not_assessable_by_testing';

export interface Finding {
  id: string;
  requirement?: string;
  title?: string;
  verdict: Verdict | (string & {});
  confidence: number | null; // 0..1
  metric?: {
    name: string;
    value: number | null;
    ci: [number, number] | null;
    threshold?: number;
    /** The threshold as written, e.g. ">= 0.80". */
    thresholdText?: string;
    thresholdSource?: string;
  };
  evidence: { text: string; ci?: [number, number]; runId?: string }[];
  counterEvidence: string[];
  wouldChangeIf: string[];
  reasoning?: string;
  citations: Citation[];
  limitations?: string[];
  critic?: { originalVerdict?: Verdict | (string & {}); adjusted: boolean; note?: string; call?: string };
}

export interface FindingsData {
  findings: Finding[];
}

export interface CriticData {
  reviews: {
    findingId: string;
    challenge?: string;
    attempt?: string;
    outcome: 'upheld' | 'weakened' | 'overturned' | (string & {});
    newVerdict?: Verdict | (string & {});
    confidenceDelta: number | null;
    newConfidence?: number | null;
  }[];
  summary?: string;
}

export type Traffic = 'green' | 'amber' | 'red' | 'grey';

export interface ReportData {
  audience: 'engineer' | 'management';
  title?: string;
  markdown: string;
  traffic?: { requirement: string; title?: string; light: Traffic | (string & {}); note?: string }[];
  decisions?: string[];
  nextSteps?: string[];
  reproducibility?: { kbVersion: string; cardVersion: number; seeds: number[]; mlflowRuns: string[] };
}

export interface PublicCandidate {
  id: string;
  name: string;
  url?: string;
  source?: string;
  score: number | null;
  rows?: number;
  licence?: string;
  licenceStatus?: string;
  task?: string;
  fetchable: boolean;
  mapped: string[];
  missingProtected: string[];
  description?: string;
}

export interface PublicCandidatesData {
  plugin?: string;
  candidates: PublicCandidate[];
  recommendation: { mode?: string; reason?: string; candidate?: string | null };
  sources: { name: string; ok: boolean; found?: number; error?: string }[];
}

export interface TestResultRow {
  id: string;
  testId?: string;
  scenario?: string;
  requirement?: string;
  metric?: string;
  value: number | null;
  ci: [number, number] | null;
  n?: number;
  threshold?: string;
  status?: string;
  passed: boolean | null;
  runId?: string;
}

export interface TestResultsData {
  tests: TestResultRow[];
  error?: string;
  /** Mock shape: aggregate counts only. */
  summary?: { runs?: number; passed?: number; failed?: number };
}

export interface DatasetData {
  datasetId?: string;
  name?: string;
  rows?: number;
  mode?: string;
  method?: string;
  seed?: number;
  byTest: Record<string, number>;
  twinsByMode: Record<string, number>;
  population: { stat: string; stated?: number; observed?: number; ok: boolean | null }[];
  limitations: string[];
  sample: { columns: string[]; rows: Record<string, string | number>[] };
  status?: string;
  problems: string[];
}
