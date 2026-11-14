// The engineer pipeline as a graph: node positions (three phase rows), edge states and the redo
// loops a gate rejection or a verifier redo leaves behind. Pure; the React Flow view is
// components/PipelineFlow.tsx.
import { STAGES, stepStates, type StepState } from './pipeline';
import type { AuditDetail } from './types';

export const NODE_W = 196;
export const NODE_H = 68;
const GAP_X = 40;
const ROW_H = 140;

/** Phase rows, in pipeline order. */
export const PHASES: { label: string; stages: string[] }[] = [
  {
    label: 'Understand and plan',
    stages: ['load_context', 'profile_model', 'plan_scenarios', 'analyse_scenarios', 'approve_scenarios'],
  },
  {
    label: 'Synthetic data',
    stages: ['find_public_data', 'draft_spec', 'generate_data', 'analyse_datasets', 'approve_datasets'],
  },
  { label: 'Test and judge', stages: ['run_tests', 'analyse', 'critic', 'report'] },
];

export function nodePosition(stageId: string): { x: number; y: number; row: number } {
  for (let row = 0; row < PHASES.length; row++) {
    const col = PHASES[row].stages.indexOf(stageId);
    if (col >= 0) return { x: col * (NODE_W + GAP_X), y: row * ROW_H, row };
  }
  return { x: 0, y: 0, row: 0 };
}

export type EdgeState = 'done' | 'live' | 'waiting' | 'pending';

/** State of the edge from one step to the next: "live" / "waiting" lead into the current step. */
export function edgeState(from: StepState, to: StepState): EdgeState {
  if (to === 'active') return 'live';
  if (to === 'needs-approval') return 'waiting';
  if (from === 'done' && to !== 'pending') return 'done';
  return 'pending';
}

export interface PipelineEdge {
  id: string;
  source: string;
  target: string;
  state: EdgeState;
  /** Same row (left to right) or a wrap to the start of the next phase row. */
  wrap: boolean;
}

export function pipelineEdges(states: Record<string, StepState>): PipelineEdge[] {
  return STAGES.slice(1).map((s, i) => {
    const prev = STAGES[i];
    return {
      id: `${prev.id}->${s.id}`,
      source: prev.id,
      target: s.id,
      state: edgeState(states[prev.id], states[s.id]),
      wrap: nodePosition(prev.id).row !== nodePosition(s.id).row,
    };
  });
}

/** Where each gate (and its verifier) sends the run back, and which artifact kind the redo rewrites. */
export const REDO_LOOPS = [
  { gate: 'scenarios', from: 'approve_scenarios', to: 'plan_scenarios', kind: 'scenarios' },
  { gate: 'datasets', from: 'approve_datasets', to: 'draft_spec', kind: 'generation_spec' },
] as const;

export interface RedoLoop {
  id: string;
  source: string;
  target: string;
  /** Times the step was redone (versions of its artifact - 1, at least the gate's send-backs). */
  count: number;
  /** Gate decisions that sent it back. */
  rejections: number;
}

/** Redo loops that actually happened in this audit (none on a clean run). */
export function redoLoops(audit: Pick<AuditDetail, 'artifacts' | 'approvals'>): RedoLoop[] {
  const out: RedoLoop[] = [];
  for (const l of REDO_LOOPS) {
    const versions = audit.artifacts.filter((a) => a.kind === l.kind && a.name === 'main').length;
    const maxVersion = Math.max(0, ...audit.artifacts.filter((a) => a.kind === l.kind).map((a) => a.version));
    const rejections = audit.approvals.filter((p) => p.gate === l.gate && p.decision !== 'approved').length;
    const count = Math.max(rejections, Math.max(versions, maxVersion) - 1);
    if (count > 0) out.push({ id: `redo-${l.gate}`, source: l.from, target: l.to, count, rejections });
  }
  return out;
}

export function graphModel(audit: AuditDetail) {
  const states = stepStates(audit);
  return { states, edges: pipelineEdges(states), redos: redoLoops(audit) };
}
