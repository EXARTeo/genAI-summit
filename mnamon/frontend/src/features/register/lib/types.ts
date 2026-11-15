// Findings register (backend `schema/register.py`, snake_case like the sealed findings): the
// system's state per obligation across audits.

export type RegisterState = 'open' | 'closed' | 'resolved' | 'monitoring';

/** What one audit meant for an item (also stamped on sealed findings as `data.register_status`). */
export type RegisterStatus = 'new' | 'still_open' | 'resolved' | 'regressed' | 'accepted_risk' | 'unchanged';

export interface RegisterEvent {
  at: string;
  audit_id: string | null;
  finding_id?: string | null;
  actor: string;
  /** opened | first_seen | still_open | verdict_changed | resolved | regressed | closed | reopened | checked */
  kind: string;
  from: string | null;
  to: string | null;
  verdict: string | null;
  previous_verdict?: string | null;
  note: string | null;
}

export interface RegisterItem {
  id: string;
  system_id: string;
  obligation_id: string;
  state: RegisterState | (string & {});
  verdict: string;
  severity: string | null;
  article: string | null;
  title: string | null;
  gap_id: string | null;
  first_seen_audit_id: string;
  last_seen_audit_id: string;
  last_finding_id: string | null;
  opened_at: string | null;
  closed_by: string | null;
  close_reason: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
  last_status: RegisterStatus | (string & {}) | null;
  last_reasoning: string | null;
  last_evidence: string[];
  history: RegisterEvent[];
}

export interface RegisterSummary {
  total: number;
  by_state: Record<string, number>;
  by_verdict: Record<string, number>;
  open_gaps: number;
  needs_review: number;
  accepted_risks: number;
  resolved: number;
  monitoring: number;
}

export interface Register {
  system_id: string;
  summary: RegisterSummary;
  items: RegisterItem[];
}
