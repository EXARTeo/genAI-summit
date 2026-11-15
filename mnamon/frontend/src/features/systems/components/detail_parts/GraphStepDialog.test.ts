import { describe, expect, it } from 'vitest';
import type { GraphComponent, PluginGraph } from '../../lib/types';
import { exampleStep, nextExampleModel } from './GraphStepDialog';

const comp = (over: Partial<GraphComponent>): GraphComponent => ({
  id: 'SYS-009.x',
  name: 'X',
  kind: '',
  configured: false,
  testable: false,
  ...over,
});

const graph = (components: GraphComponent[]): PluginGraph => ({
  system: 'SYS-009',
  components,
  edges: [],
  plugins: {},
});

describe('fill example for a graph step', () => {
  it('an empty graph gets the first seed model, with no connections', () => {
    const ex = exampleStep(graph([]), 'ml_model');
    expect(ex).toEqual({
      name: 'CV parser',
      model: 'models:/sys-001-cv-parser@champion',
      upstream: '',
      downstream: '',
    });
  });

  it('a model extends the pipeline and skips seed models already used', () => {
    const g = graph([
      comp({ id: 'SYS-009.portal', name: 'Applicant portal', kind: 'upstream_system' }),
      comp({
        id: 'SYS-009.cv-parser',
        name: 'CV parser',
        testable: true,
        model: 'models:/sys-001-cv-parser@champion',
      }),
    ]);
    expect(nextExampleModel(g).folder).toBe('cv-ranker');
    expect(exampleStep(g, 'ml_model').upstream).toBe('SYS-009.cv-parser');
  });

  it('an upstream system feeds the first model, a human step follows the last box', () => {
    const g = graph([comp({ id: 'SYS-009.m', name: 'M', testable: true })]);
    expect(exampleStep(g, 'upstream_system')).toMatchObject({
      name: 'Applicant portal',
      downstream: 'SYS-009.m',
    });
    expect(exampleStep(g, 'human_review')).toMatchObject({
      name: 'Recruiter review',
      upstream: 'SYS-009.m',
    });
  });
});
