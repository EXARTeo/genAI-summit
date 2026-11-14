// The engineer pipeline as a graph: three phase lanes (cards stacked in each), edge states and the redo
// loops a gate rejection or a verifier redo leaves behind. Pure; the React Flow view is
// components/PipelineFlow.tsx.
import { STAGES, stepStates, type StepState } from './pipeline';
import type { AuditDetail } from './types';

/** Phase lanes, in pipeline order; each one ends at a human gate (the last one at the report). */
export const PHASES: { id: string; label: string; stages: string[] }[] = [
  {
    id: 'plan',
    label: 'Understand & plan',
    stages: ['load_context', 'profile_model', 'plan_scenarios', 'analyse_scenarios', 'approve_scenarios'],
  },
  {
    id: 'data',
    label: 'Synthetic data',
    stages: ['find_public_data', 'draft_spec', 'generate_data', 'analyse_datasets', 'approve_datasets'],
  },
  { id: 'test', label: 'Test & judge', stages: ['run_tests', 'analyse', 'critic', 'report'] },
];

/** Lane geometry (px, drawn at zoom 1 so card text is its real size). */
export const LANE = { gutter: 44, pad: 14, header: 54, gapY: 30, minWidth: 900 } as const;

export function phaseOf(stageId: string): number {
  return PHASES.findIndex((p) => p.stages.includes(stageId));
}

export interface LaneLayout {
  laneWidth: number;
  cardWidth: number;
  height: number;
  lanes: { id: string; x: number }[];
  positions: Record<string, { x: number; y: number; height: number }>;
}

/**
 * Three lanes side by side filling `width`; cards stacked top to bottom inside each lane,
 * `heightOf(stage)` tall (a waiting gate is taller: it carries its decision button).
 */
export function laneLayout(width: number, heightOf: (stageId: string) => number): LaneLayout {
  const w = Math.max(width, LANE.minWidth);
  const laneWidth = (w - LANE.gutter * (PHASES.length - 1)) / PHASES.length;
  const cardWidth = laneWidth - LANE.pad * 2;
  const positions: LaneLayout['positions'] = {};
  let height = 0;
  const lanes = PHASES.map((p, i) => {
    const x = i * (laneWidth + LANE.gutter);
    let y = LANE.header;
    for (const id of p.stages) {
      const h = heightOf(id);
      positions[id] = { x: x + LANE.pad, y, height: h };
      y += h + LANE.gapY;
    }
    height = Math.max(height, y - LANE.gapY + LANE.pad);
    return { id: p.id, x };
  });
  return { laneWidth, cardWidth, height, lanes, positions };
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
      wrap: phaseOf(prev.id) !== phaseOf(s.id),
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
