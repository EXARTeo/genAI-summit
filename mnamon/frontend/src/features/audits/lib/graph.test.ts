import { describe, expect, it } from 'vitest';
import { reviewedScenarios, searchDrivers, stepMemory, toScenarios } from './adapters';
import real from './fixtures/sys001-audit.json';
import { GRAPH, PHASES, edgeState, graphLayout, graphModel, phaseOf, redoLoops } from './graph';
import { stepSummary } from './stepMeta';
import { STAGES } from './pipeline';
import type { Approval, Artifact, AuditDetail } from './types';

const audit = real as unknown as AuditDetail;

describe('pipeline graph', () => {
  it('places every stage exactly once, in pipeline order per row', () => {
    expect(PHASES.flatMap((p) => p.stages)).toEqual(STAGES.map((s) => s.id));
    expect(phaseOf('pin')).toBe(0);
    expect(phaseOf('approve_scenarios')).toBe(1);
    expect(phaseOf('find_public_data')).toBe(2);
    expect(phaseOf('seal')).toBe(3);
    const l = graphLayout(1100, (id) => id === 'approve_datasets');
    expect(l.positions.load_context.y).toBe(l.positions.profile_model.y);
    expect(l.positions.plan_scenarios.y).toBe(l.positions.approve_scenarios.y);
    expect(l.positions.find_public_data.x).toBe(l.positions.load_context.x);
    expect(l.positions.draft_spec.x).toBeCloseTo(l.positions.find_public_data.x + l.colWidth);
    expect(l.positions.find_public_data.y).toBeGreaterThan(l.positions.approve_scenarios.y);
    expect(l.positions.approve_datasets.height).toBe(GRAPH.box + GRAPH.label + GRAPH.action);
    expect(l.positions.load_context.height).toBe(GRAPH.box + GRAPH.label);
    expect(l.height).toBe(l.groups[3].y + l.groups[3].height);
  });

  it('edges lead into the live step and wrap between rows', () => {
    const { edges, states } = graphModel(audit);
    expect(states.approve_datasets).toBe('needs-approval');
    expect(edges.find((e) => e.target === 'approve_datasets')?.state).toBe('waiting');
    expect(edges.find((e) => e.target === 'run_inference')?.state).toBe('pending');
    expect(edges.find((e) => e.source === 'approve_scenarios')?.wrap).toBe(true);
    expect(edgeState('done', 'active')).toBe('live');
  });

  it('shows no redo loop on a clean run, one after a rejection', () => {
    expect(redoLoops(audit)).toEqual([]);
    const rejected: Approval = { ...audit.approvals[0], id: 'x', decision: 'changes_requested' };
    const v2 = { ...audit.artifacts.find((a) => a.kind === 'scenarios')!, id: 'v2', version: 2 } as Artifact;
    const loops = redoLoops({
      artifacts: [...audit.artifacts, v2],
      approvals: [...audit.approvals, rejected],
    });
    expect(loops).toEqual([
      {
        id: 'redo-scenarios',
        source: 'approve_scenarios',
        target: 'plan_scenarios',
        count: 1,
        rejections: 1,
      },
    ]);
  });
});

describe('scenario relevance review', () => {
  const data = toScenarios({
    scenarios: [
      {
        id: 'SC-01',
        review: {
          model: 'iris',
          verdict: 'relevant',
          rationale: 'ok',
          suggested_change: null,
          confidence: 0.9,
        },
      },
      {
        id: 'SC-02',
        review: {
          model: 'gemini',
          verdict: 'needs_change',
          rationale: 'n too small',
          suggested_change: 'n=800',
        },
      },
      { id: 'SC-03', review: { model: 'iris', verdict: 'not_relevant', rationale: 'no such field' } },
      { id: 'SC-04' },
      { id: 'SC-05', review: { verdict: 'bogus' } },
    ],
  });

  it('parses the optional review', () => {
    expect(data.scenarios[1].review).toEqual({
      model: 'gemini',
      verdict: 'needs_change',
      rationale: 'n too small',
      suggestedChange: 'n=800',
      confidence: null,
    });
    expect(data.scenarios[3].review).toBeUndefined();
    expect(data.scenarios[4].review).toBeUndefined();
  });

  it('orders not_relevant, needs_change, relevant', () => {
    expect(reviewedScenarios(data).map((s) => s.id)).toEqual(['SC-03', 'SC-02', 'SC-01']);
  });

  it('is absent on the live (older) audit', () => {
    const live = toScenarios(audit.artifacts.find((a) => a.kind === 'scenarios')!.data);
    expect(live.scenarios.every((s) => s.review === undefined)).toBe(true);
  });

  it('collects memory read and written by a step', () => {
    const m = stepMemory([
      {
        data: { scenarios: [{ memory_applied: ['audits/a/lesson.md'] }], lessons_recorded: ['proxy-twins'] },
      } as unknown as Artifact,
    ]);
    expect(m).toEqual({ applied: ['audits/a/lesson.md'], recorded: ['proxy-twins'] });
  });
});

describe('public data search drivers', () => {
  it('derives the scenarios behind the search from the fields they need', () => {
    const cand = audit.artifacts.find((a) => a.kind === 'public_dataset_candidates')!.data;
    const plan = audit.artifacts.find((a) => a.kind === 'scenarios')!.data;
    const { explicit, drivers } = searchDrivers(cand, plan);
    expect(explicit).toBe(false);
    expect(drivers.map((d) => d.id)).toEqual(['SC-01', 'SC-02', 'SC-03', 'SC-04', 'SC-06']);
    expect(searchDrivers({ scenarios: ['SC-05'] }, plan)).toMatchObject({
      explicit: true,
      drivers: [{ id: 'SC-05', fields: ['years_experience'] }],
    });
  });
});

describe('step summaries', () => {
  it('says what each step produced, and the gate decision', () => {
    expect(stepSummary('load_context', audit)).toMatch(/^\d+ requirements · \d+ testable$/);
    expect(stepSummary('generate_data', audit)).toBe('3,654 rows · 3,123 twins');
    expect(stepSummary('approve_scenarios', audit)).toBe('Approved');
    expect(stepSummary('run_inference', audit)).toBeUndefined();
  });
});
