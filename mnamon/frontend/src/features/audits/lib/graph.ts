// The engineer pipeline as a graph: four phase bands (one row of nodes each), edge states and the redo
// loops a gate rejection or a verifier redo leaves behind. Pure; the React Flow view is
// components/PipelineFlow.tsx.
import { STAGES, stepStates, type StepState } from './pipeline';
import type { AuditDetail } from './types';

/** Phase lanes, in pipeline order; each one ends at a human gate (the last one at the report). */
export const PHASES: { id: string; label: string; stages: string[] }[] = [
  {
    id: 'ground',
    label: 'Ground in the regulation',
    stages: ['load_context', 'pin', 'ground_obligations', 'profile_model'],
  },
  {
    id: 'plan',
    label: 'Plan scenarios',
    stages: ['plan_scenarios', 'analyse_scenarios', 'approve_scenarios'],
  },
  {
    id: 'data',
    label: 'Synthetic data',
    stages: ['find_public_data', 'draft_spec', 'generate_data', 'analyse_datasets', 'approve_datasets'],
  },
  {
    id: 'test',
    label: 'Test & judge',
    stages: ['run_inference', 'analyse_results', 'assess_obligations', 'critic', 'seal', 'report'],
  },
];

/**
 * Graph geometry (px, drawn at zoom 1 so text is its real size). Each phase is a band with
 * one row of nodes, left to right, on a shared six-column grid; a node is an icon box with
 * its label under it (a waiting gate adds its decision button below the label).
 */
export const GRAPH = {
  padX: 16,
  header: 40,
  box: 60,
  label: 56,
  action: 40,
  padBottom: 16,
  groupGap: 34,
  columns: 6,
  minWidth: 720,
} as const;

export function phaseOf(stageId: string): number {
  return PHASES.findIndex((p) => p.stages.includes(stageId));
}

export interface GraphLayout {
  width: number;
  colWidth: number;
  height: number;
  groups: { id: string; y: number; height: number }[];
  /** Node frame (column-wide); the icon box sits centred at its top. */
  positions: Record<string, { x: number; y: number; height: number }>;
}

/** Phase bands stacked top to bottom; `hasAction(stage)` = the node carries a decision button. */
export function graphLayout(width: number, hasAction: (stageId: string) => boolean): GraphLayout {
  const w = Math.max(width, GRAPH.minWidth);
  const colWidth = (w - GRAPH.padX * 2) / GRAPH.columns;
  const positions: GraphLayout['positions'] = {};
  let y = 0;
  const groups = PHASES.map((p) => {
    const rowH = GRAPH.box + GRAPH.label + (p.stages.some(hasAction) ? GRAPH.action : 0);
    p.stages.forEach((id, i) => {
      positions[id] = { x: GRAPH.padX + i * colWidth, y: y + GRAPH.header, height: rowH };
    });
    const g = { id: p.id, y, height: GRAPH.header + rowH + GRAPH.padBottom };
    y += g.height + GRAPH.groupGap;
    return g;
  });
  return { width: w, colWidth, height: y - GRAPH.groupGap, groups, positions };
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
