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

export type MemoryScope = 'none' | 'system' | 'org';

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
    if (a.status !== 'waiting_approval' && a.status !== 'running') continue;
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
  memoryScope: MemoryScope;
}

export const EMPTY_DRAFT: DecisionDraft = {
  decision: null,
  reasonCategory: null,
  comment: '',
  memoryScope: 'none',
};

/** Validation errors for a draft; empty = valid. A reason category is mandatory for every decision. */
export function validateDraft(d: DecisionDraft): string[] {
  const errors: string[] = [];
  if (!d.decision) errors.push('Choose a decision.');
  if (!d.reasonCategory) errors.push('Pick a reason category.');
  if (d.decision && d.decision !== 'approved' && d.comment.trim().length < 5)
    errors.push('Say what should change (comment).');
  if (d.memoryScope !== 'none' && d.comment.trim().length < 5)
    errors.push('A memory needs a comment that explains it.');
  return errors;
}

/** Build the backend ApprovalIn; memory preference travels in `edits` (flexible JSONB). */
export function toApprovalIn(gate: string, d: DecisionDraft, artifactId?: string | null): ApprovalIn {
  if (validateDraft(d).length) throw new Error('invalid decision draft');
  return {
    gate,
    decision: d.decision!,
    artifactId: artifactId ?? null,
    reasonCategory: d.reasonCategory,
    comment: d.comment.trim() || null,
    edits: d.memoryScope === 'none' ? {} : { memory: { scope: d.memoryScope } },
  };
}
