// Pure HITL-gate logic: which gates are open, reason categories, payload validation.
import { STAGES, gateStage, stageIndex } from '@/features/audits/lib/pipeline';
import type { ApprovalIn, AuditDetail, Decision, ReasonCategory } from '@/features/audits/lib/types';

export const REASONS: { value: ReasonCategory; label: string; hint: string }[] = [
  { value: 'wrong_fact', label: 'Wrong fact', hint: 'A stated fact about the system or the law is wrong' },
  {
    value: 'wrong_interpretation',
    label: 'Wrong interpretation',
    hint: 'The reading of a provision or a result is wrong',
  },
  { value: 'missing_info', label: 'Missing info', hint: 'Something the agent should have used is missing' },
  { value: 'wrong_metric', label: 'Wrong metric', hint: 'The metric does not fit the use case' },
  {
    value: 'unrealistic_data',
    label: 'Unrealistic data',
    hint: 'Synthetic data does not match the real population',
  },
  { value: 'org_policy', label: 'Org policy', hint: 'Conflicts with an organisational policy' },
  { value: 'other', label: 'Other', hint: 'Explain in the comment' },
];

export const DECISIONS: Record<Decision, { label: string; tone: 'success' | 'warning' | 'danger' }> = {
  approved: { label: 'Approve', tone: 'success' },
  changes_requested: { label: 'Request changes', tone: 'warning' },
  rejected: { label: 'Reject', tone: 'danger' },
};

export interface OpenGate {
  auditId: string;
  systemId: string;
  systemName: string;
  auditTitle: string;
  gate: string; // "scenarios" | "datasets"
  stageId: string;
  label: string;
  waitingSince: string;
  artifactIds: string[];
}

/** Open HITL gates: audits paused at a gate stage that has no decision yet for this run. */
export function openGates(audits: AuditDetail[]): OpenGate[] {
  const out: OpenGate[] = [];
  for (const a of audits) {
    const i = stageIndex(a.stage);
    const stage = STAGES[i];
    if (!stage?.gate) continue;
    // A working stage with a gate (find_public_data) is open only once it waits.
    const waits = a.status === 'waiting_approval' || (a.status === 'running' && stage.kinds.length === 0);
    if (!waits) continue;
    const decided = a.approvals.some(
      (p) => p.gate === stage.gate!.id && p.decision === 'approved' && p.at >= a.updatedAt,
    );
    if (decided) continue;
    const reviewed = new Set<string>(stage.gate.reviews);
    out.push({
      auditId: a.id,
      systemId: a.systemId,
      systemName: (a.data.systemName as string) ?? a.systemId,
      auditTitle: (a.data.title as string) ?? 'Audit',
      gate: stage.gate.id,
      stageId: stage.id,
      label: stage.label,
      waitingSince: a.updatedAt,
      artifactIds: a.artifacts
        .filter((x) => reviewed.has(x.kind) && x.status !== 'superseded')
        .map((x) => x.id),
    });
  }
  return out.sort((x, y) => x.waitingSince.localeCompare(y.waitingSince));
}

export function gateLabel(gate: string): string {
  return gateStage(gate)?.label ?? gate;
}

export interface DecisionDraft {
  decision: Decision | null;
  reasonCategory: ReasonCategory | null;
  comment: string;
}

export const EMPTY_DRAFT: DecisionDraft = {
  decision: null,
  reasonCategory: null,
  comment: '',
};

/** Validation errors for a draft; empty = valid. A reason category is mandatory for every decision. */
export function validateDraft(d: DecisionDraft): string[] {
  const errors: string[] = [];
  if (!d.decision) errors.push('Choose a decision.');
  if (!d.reasonCategory) errors.push('Pick a reason category.');
  if (d.decision && d.decision !== 'approved' && d.comment.trim().length < 5)
    errors.push('Say what should change (comment).');
  return errors;
}

/** Build the backend ApprovalIn. What to remember from a decision is up to the agents. */
export function toApprovalIn(
  gate: string,
  d: DecisionDraft,
  artifactId?: string | null,
  edits: Record<string, unknown> = {},
): ApprovalIn {
  if (validateDraft(d).length) throw new Error('invalid decision draft');
  return {
    gate,
    decision: d.decision!,
    artifactId: artifactId ?? null,
    reasonCategory: d.reasonCategory,
    comment: d.comment.trim() || null,
    edits,
  };
}

/**
 * The public_data gate's edits: the picked candidate id goes to the pipeline as `edits.selected`
 * (agents/pipeline/graph.py gate_public_data). Approve needs a pick; any other decision makes the
 * pipeline continue zero-shot from the data dictionary (the run does not stop at this gate).
 */
export function publicDataEdits(selected: string | null): Record<string, unknown> {
  return selected ? { selected } : {};
}

/** The reason the pipeline records when the reviewer leaves "Why exclude?" empty. */
export const DEFAULT_EXCLUDE_REASON = 'excluded by the reviewer';

/**
 * The scenarios gate's default selection: every scenario except the ones the scenario judge
 * (Iris or Gemini) reviewed as `not_relevant`. Plan order is kept.
 */
export function defaultScenarioSelection(
  scenarios: { id: string; review?: { verdict: string } }[],
): string[] {
  return scenarios.filter((s) => s.review?.verdict !== 'not_relevant').map((s) => s.id);
}

/**
 * The scenarios gate's edits for a partial approval (agents/pipeline/graph.py _keep_approved):
 * `approved_scenarios` lists the kept ids in plan order, `excluded` maps every other id to the
 * reviewer's reason (empty reason -> the default). Everything approved -> `{}` (no selection,
 * the pipeline keeps every scenario). Zero approved is not a valid approval; the UI asks for
 * "Request changes" instead.
 */
export function scenarioEdits(
  approved: string[],
  all: string[],
  reasons: Record<string, string> = {},
): Record<string, unknown> {
  const keep = new Set(approved);
  const kept = all.filter((id) => keep.has(id));
  const dropped = all.filter((id) => !keep.has(id));
  if (dropped.length === 0) return {};
  return {
    approved_scenarios: kept,
    excluded: Object.fromEntries(dropped.map((id) => [id, reasons[id]?.trim() || DEFAULT_EXCLUDE_REASON])),
  };
}
