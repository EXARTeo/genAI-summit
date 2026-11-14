import { describe, expect, it } from 'vitest';
import { buildMockAudits } from './mocks';
import {
  STAGES,
  artifactsForStage,
  defaultSelectedStage,
  gateStage,
  latestByKind,
  progress,
  stageForKind,
  stageIndex,
  stepState,
  stepStates,
} from './pipeline';
import type { Artifact } from './types';

describe('stage mapping', () => {
  it('has the 14 pipeline stages with three HITL gates', () => {
    expect(STAGES).toHaveLength(14);
    expect(STAGES.filter((s) => s.gate).map((s) => s.id)).toEqual([
      'approve_scenarios',
      'find_public_data',
      'approve_datasets',
    ]);
  });

  it('find_public_data runs, then waits at the public_data gate', () => {
    expect(stepState('find_public_data', { stage: 'find_public_data', status: 'running' })).toBe('active');
    expect(stepState('find_public_data', { stage: 'find_public_data', status: 'waiting_approval' })).toBe(
      'needs-approval',
    );
    expect(stepState('approve_scenarios', { stage: 'approve_scenarios', status: 'running' })).toBe(
      'needs-approval',
    );
    expect(gateStage('public_data')?.id).toBe('find_public_data');
  });

  it('accepts artifact-kind aliases for backend stages', () => {
    expect(stageIndex('context')).toBe(0);
    expect(stageIndex('dataset_analysis')).toBe(stageIndex('analyse_datasets'));
    expect(stageIndex('nope')).toBe(-1);
  });

  it('maps artifact kinds to stages', () => {
    expect(stageForKind('generation_spec')?.id).toBe('draft_spec');
    expect(stageForKind('finding')?.id).toBe('analyse');
    expect(stageForKind('unknown')).toBeUndefined();
  });
});

describe('stepState', () => {
  it('marks earlier steps done, the current active and later pending while running', () => {
    const audit = { stage: 'generate_data', status: 'running' };
    expect(stepState('load_context', audit)).toBe('done');
    expect(stepState('generate_data', audit)).toBe('active');
    expect(stepState('report', audit)).toBe('pending');
  });

  it('shows needs-approval on a gate the run has reached', () => {
    expect(stepState('approve_datasets', { stage: 'approve_datasets', status: 'waiting_approval' })).toBe(
      'needs-approval',
    );
    expect(stepState('approve_datasets', { stage: 'approve_datasets', status: 'running' })).toBe(
      'needs-approval',
    );
  });

  it('blocks the current step when the run failed', () => {
    expect(stepState('run_tests', { stage: 'run_tests', status: 'failed' })).toBe('blocked');
  });

  it('marks everything done when the audit is done', () => {
    const states = stepStates({ stage: 'report', status: 'done' });
    expect(Object.values(states).every((s) => s === 'done')).toBe(true);
  });

  it('computes progress and the default selection', () => {
    expect(progress({ stage: 'load_context', status: 'running' })).toBe(0);
    expect(progress({ stage: 'report', status: 'done' })).toBe(1);
    expect(defaultSelectedStage({ stage: 'approve_datasets', status: 'waiting_approval' })).toBe(
      'approve_datasets',
    );
    expect(defaultSelectedStage({ stage: 'x', status: 'done' })).toBe('report');
  });
});

describe('artifacts', () => {
  const base: Artifact = {
    id: 'a1',
    auditId: 'x',
    kind: 'scenarios',
    name: 'main',
    version: 1,
    status: 'approved',
    data: {},
    fileRefs: [],
    parentId: null,
    createdBy: 'agent',
    createdAt: '',
    updatedAt: '',
  };

  it('keeps the latest non-superseded version per (kind, name)', () => {
    const list = [
      base,
      { ...base, id: 'a2', version: 2, status: 'proposed' },
      { ...base, id: 'a3', version: 3, status: 'superseded' },
    ];
    expect(latestByKind(list).scenarios?.map((a) => a.id)).toEqual(['a2']);
  });

  it('shows the reviewed artifacts on a gate step', () => {
    const audit = buildMockAudits()[0];
    const gate = STAGES.find((s) => s.id === 'approve_datasets')!;
    expect(artifactsForStage(gate, audit.artifacts).map((a) => a.kind)).toEqual([
      'generation_spec',
      'dataset_analysis',
    ]);
  });

  it('returns both reports for the report step', () => {
    const done = buildMockAudits().find((a) => a.status === 'done')!;
    const report = STAGES.find((s) => s.id === 'report')!;
    expect(artifactsForStage(report, done.artifacts).map((a) => a.name)).toEqual(['engineer', 'management']);
  });
});
