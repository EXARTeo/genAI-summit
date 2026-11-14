// The engineer pipeline as a deterministic list of stages, and the pure logic that maps
// an audit's (stage, status) + artifacts onto per-step states for the Stepper.
import type { Artifact, ArtifactKind, Audit, AuditStatus } from './types';

export type StepState = 'done' | 'active' | 'pending' | 'blocked' | 'needs-approval';

export interface StageDef {
  id: string;
  label: string;
  description: string;
  /** Artifact kinds this stage produces (shown in the right panel). */
  kinds: ArtifactKind[];
  /** HITL gate: the stage waits for a human decision (after its own work, if it has kinds). */
  gate?: { id: string; reviews: ArtifactKind[] };
}

export const STAGES: StageDef[] = [
  {
    id: 'load_context',
    label: 'Load context',
    description: 'System card, plugins, applicable requirements, business rules',
    kinds: ['context'],
  },
  {
    id: 'profile_model',
    label: 'Profile model',
    description: 'Probe the model: feature sensitivity and decision boundaries',
    kinds: ['model_profile'],
  },
  {
    id: 'find_public_data',
    label: 'Find public data',
    description: 'Search public datasets as a reference sample; a person picks one or none',
    kinds: ['public_dataset_candidates'],
    gate: { id: 'public_data', reviews: ['public_dataset_candidates'] },
  },
  {
    id: 'plan_scenarios',
    label: 'Plan scenarios',
    description: 'Requirement → test templates, parameterised from the card',
    kinds: ['scenarios'],
  },
  {
    id: 'analyse_scenarios',
    label: 'Analyse scenarios',
    description: 'Coverage per requirement, what testing cannot show',
    kinds: ['scenario_analysis'],
  },
  {
    id: 'approve_scenarios',
    label: 'Approve scenarios',
    description: 'Human gate: approve, edit or reject the test plan',
    kinds: [],
    gate: { id: 'scenarios', reviews: ['scenarios', 'scenario_analysis'] },
  },
  {
    id: 'draft_spec',
    label: 'Draft generation spec',
    description: 'GenerationSpec with provenance per field',
    kinds: ['generation_spec'],
  },
  {
    id: 'generate_data',
    label: 'Generate data',
    description: 'DAG sampler, rule repair, counterfactual twins',
    kinds: ['dataset'],
  },
  {
    id: 'analyse_datasets',
    label: 'Analyse datasets',
    description: 'Five gates, coverage, twin pairs, Data Card',
    kinds: ['dataset_analysis'],
  },
  {
    id: 'approve_datasets',
    label: 'Approve datasets',
    description: 'Human gate: audit the synthetic data before any test runs',
    kinds: [],
    gate: { id: 'datasets', reviews: ['generation_spec', 'dataset_analysis'] },
  },
  {
    id: 'run_tests',
    label: 'Run tests',
    description: 'Sandbox; one MLflow run per test',
    kinds: ['test_plan', 'test_result'],
  },
  {
    id: 'analyse',
    label: 'Analyse',
    description: 'Findings with evidence, CI and counter-evidence',
    kinds: ['finding'],
  },
  {
    id: 'critic',
    label: 'Critic',
    description: 'A separate agent tries to overturn each finding',
    kinds: ['critic'],
  },
  {
    id: 'report',
    label: 'Report',
    description: 'Engineer report + management traffic lights',
    kinds: ['report'],
  },
];

const ALIASES: Record<string, string> = {
  context: 'load_context',
  model_profile: 'profile_model',
  public_dataset_candidates: 'find_public_data',
  gate_public_data: 'find_public_data',
  public_data: 'find_public_data',
  scenarios: 'plan_scenarios',
  scenario_analysis: 'analyse_scenarios',
  generation_spec: 'draft_spec',
  dataset: 'generate_data',
  dataset_analysis: 'analyse_datasets',
  execute: 'run_tests',
  test_result: 'run_tests',
  findings: 'analyse',
  finding: 'analyse',
  reports: 'report',
};

/** Index of a backend stage id in STAGES (accepts artifact-kind style aliases). -1 if unknown. */
export function stageIndex(stage: string): number {
  const id = ALIASES[stage] ?? stage;
  return STAGES.findIndex((s) => s.id === id);
}

export function stageForKind(kind: string): StageDef | undefined {
  return STAGES.find((s) => s.kinds.includes(kind as ArtifactKind));
}

export function gateStage(gateId: string): StageDef | undefined {
  return STAGES.find((s) => s.gate?.id === gateId || s.id === gateId);
}

/** Per-step state from the audit's current stage and status. */
export function stepState(stageId: string, audit: Pick<Audit, 'stage' | 'status'>): StepState {
  const i = stageIndex(stageId);
  const cur = stageIndex(audit.stage);
  const status: AuditStatus = audit.status;
  if (status === 'done' || status === 'completed') return 'done';
  if (i < 0 || cur < 0) return 'pending';
  if (i < cur) return 'done';
  if (i > cur) return 'pending';
  if (status === 'failed') return 'blocked';
  // A pure gate stage (no work of its own) waits; a working stage with a gate
  // (find_public_data) runs first, then waits for the pick.
  if (STAGES[i].gate && STAGES[i].kinds.length === 0)
    return status === 'waiting_approval' || status === 'running' ? 'needs-approval' : 'pending';
  if (status === 'waiting_approval') return 'needs-approval';
  return status === 'running' || status === 'open' ? 'active' : 'pending';
}

export function stepStates(audit: Pick<Audit, 'stage' | 'status'>): Record<string, StepState> {
  return Object.fromEntries(STAGES.map((s) => [s.id, stepState(s.id, audit)]));
}

/** 0..1 progress for rings and list rows. */
export function progress(audit: Pick<Audit, 'stage' | 'status'>): number {
  if (audit.status === 'done' || audit.status === 'completed') return 1;
  const cur = stageIndex(audit.stage);
  return cur < 0 ? 0 : cur / STAGES.length;
}

/** Latest live (non-superseded) artifact per kind, highest version wins. */
export function latestByKind(artifacts: Artifact[]): Partial<Record<string, Artifact[]>> {
  const out: Record<string, Artifact[]> = {};
  const best = new Map<string, Artifact>();
  for (const a of artifacts) {
    if (a.status === 'superseded') continue;
    const key = `${a.kind}/${a.name}`;
    const prev = best.get(key);
    if (!prev || a.version > prev.version) best.set(key, a);
  }
  for (const a of best.values()) (out[a.kind] ??= []).push(a);
  for (const list of Object.values(out)) list.sort((x, y) => x.name.localeCompare(y.name));
  return out;
}

/** Artifacts to show for a stage (for a gate: the artifacts it reviews). */
export function artifactsForStage(stage: StageDef, artifacts: Artifact[]): Artifact[] {
  const by = latestByKind(artifacts);
  const kinds = stage.gate ? stage.gate.reviews : stage.kinds;
  return kinds.flatMap((k) => by[k] ?? []);
}

/** The stage to select by default: the active / waiting one, else the last one. */
export function defaultSelectedStage(audit: Pick<Audit, 'stage' | 'status'>): string {
  if (audit.status === 'done' || audit.status === 'completed') return 'report';
  const i = stageIndex(audit.stage);
  return i >= 0 ? STAGES[i].id : STAGES[0].id;
}

export function statusLabel(status: AuditStatus): string {
  switch (status) {
    case 'waiting_approval':
      return 'Waiting for you';
    case 'running':
      return 'Running';
    case 'done':
    case 'completed':
      return 'Done';
    case 'failed':
      return 'Failed';
    default:
      return 'Open';
  }
}

export function formatDuration(seconds?: number): string {
  if (seconds == null) return '';
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  const m = Math.floor(seconds / 60);
  return `${m} m ${Math.round(seconds % 60)} s`;
}
