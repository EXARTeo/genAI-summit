// Risk classification (plan 02 §7-§8). `ClassificationResult` mirrors the agents'
// pydantic model (snake_case, stored as-is in `system_classifications.result`); the row and
// its events are normalised by `toClassification` (the backend may send camelCase).

export type ClassStatus =
  | 'running'
  | 'proposed'
  | 'failed'
  | 'approved'
  | 'rejected'
  | 'stale'
  | 'superseded';

export type ResultRiskClass = 'prohibited' | 'high_risk' | 'limited_risk' | 'minimal_risk' | 'out_of_scope';

export type Route =
  | 'art5'
  | 'art6_1_annex_i'
  | 'art6_2_annex_iii'
  | 'art6_3_exempt'
  | 'art50_only'
  | 'none'
  | 'not_ai_system';

export interface Screening {
  provision_id: string;
  applies: boolean;
  why: string;
}

export interface Art63 {
  considered: boolean;
  condition: 'a' | 'b' | 'c' | 'd' | null;
  profiling: 'yes' | 'no' | 'unknown';
  holds: boolean | null;
  why: string;
}

export interface CounterArgument {
  argument: string;
  would_change_to: string;
}

export interface Uncertainty {
  question: string;
  why_it_matters: string;
  ask: 'PM' | 'legal' | 'engineer' | string;
}

export interface Citation {
  id: string;
  kb_version?: string | null;
  quote?: string | null;
  binding: boolean;
  status?: 'final' | 'draft' | string | null;
}

export interface KeyDate {
  what: string;
  date: string;
  provision_id?: string | null;
  amended_by?: string | null;
}

export interface IrisCheck {
  choice: string;
  probabilities?: Record<string, number>;
  confidence?: number | null;
  profiling?: number | null;
}

export interface ClassificationResult {
  risk_class: ResultRiskClass | string;
  route: Route | string;
  annex_basis?: string | null;
  annex_basis_id?: string | null;
  role: 'provider' | 'deployer' | string;
  role_reasoning?: string | null;
  art5_screening: Screening[];
  annex_iii_considered: Screening[];
  art6_3?: Art63 | null;
  transparency?: { features: string[]; provisions: string[] } | null;
  gpai?: { is_gpai_model: boolean; built_on_gpai: boolean; note?: string | null } | null;
  reasoning: string;
  counter_arguments: CounterArgument[];
  would_change_if: string[];
  uncertainties: Uncertainty[];
  next_steps: string[];
  confidence: number;
  citations: Citation[];
  // Added by code.
  kb_version?: string | null;
  prechecks?: Record<string, unknown> | null;
  key_dates: KeyDate[];
  iris?: IrisCheck | null;
  agreement?: boolean | null;
  needs_human: boolean;
  needs_human_reasons: string[];
  verifier_problems: string[];
  decided_by?: string | null;
  trace_id?: string | null;
}

export interface ClassificationEvent {
  id: string;
  action: string;
  actor: string;
  reason: string | null;
  data: Record<string, unknown>;
  at: string;
}

export interface Classification {
  id: string;
  systemId: string;
  status: ClassStatus | (string & {});
  kbVersion: string | null;
  dossierVersion: Record<string, number>;
  input: Record<string, unknown>;
  result: ClassificationResult | null;
  error: string | null;
  traceId: string | null;
  previousId: string | null;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  events: ClassificationEvent[];
}

/** `GET /v1/systems/{id}/obligations`: the preview from the approved class (reg-memory rows). */
export interface ObligationsPreview {
  kb_version?: string | null;
  prohibited?: boolean;
  query?: Record<string, unknown>;
  total?: number;
  items: Record<string, unknown>[];
}
