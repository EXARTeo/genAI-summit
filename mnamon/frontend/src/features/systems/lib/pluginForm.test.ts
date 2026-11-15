import { describe, expect, it } from 'vitest';
import { cardFromForm, emptyForm, formFromCard, overrides, validateForm } from './pluginForm';
import type { PluginCard } from './types';

const defaults: PluginCard = {
  id: 'SYS-001.cv-ranker',
  system: 'SYS-001',
  name: 'Cv ranker',
  placement: { kind: 'pipeline_stage', position: '2 of 3' },
  access: {
    type: 'mlflow_model',
    uri: 'models:/sys-001-cv-ranker@champion',
    rest_url: '/v1/models/sys-001-cv-ranker/predict',
    environment: 'staging',
    auth: { type: 'bearer', secret_ref: 'env://MODEL_GATEWAY_TOKEN' },
    limits: { rps: 5, max_requests: 500, timeout_s: 10 },
  },
  io: { output: { type: 'binary_classification', label_field: 'shortlist', score_field: 'proba' } },
  expected_behaviour: { task: 'Rank applicants', must: [], must_not: [], known_limitations: [] },
};

describe('plugin form', () => {
  it('an empty form saves every default', () => {
    const card = cardFromForm(emptyForm(), defaults);
    expect(card.name).toBe('Cv ranker');
    expect(card.access.uri).toBe('models:/sys-001-cv-ranker@champion');
    expect(card.access.limits).toEqual({ rps: 5, max_requests: 500, timeout_s: 10 });
    expect(card.access.auth?.secret_ref).toBe('env://MODEL_GATEWAY_TOKEN');
    expect(card.access.url).toBeUndefined();
    expect(card.access.rest_url).toBeUndefined();
    expect(card.io?.output).toMatchObject({ label_field: 'shortlist', score_field: 'proba' });
  });

  it('typed values override, keep unshown keys of the saved card', () => {
    const existing = { ...defaults, scenarios: { personas: ['career returner'] } };
    const values = {
      ...emptyForm(),
      name: 'Candidate ranker',
      rps: '20',
      must: 'score in [0, 1]\n\n same input → same score ',
    };
    const card = cardFromForm(values, defaults, existing);
    expect(card.name).toBe('Candidate ranker');
    expect(card.access.limits?.rps).toBe(20);
    expect(card.expected_behaviour.must).toEqual(['score in [0, 1]', 'same input → same score']);
    expect(card.scenarios?.personas).toEqual(['career returner']);
    expect(overrides(values, formFromCard(defaults))).toEqual(['name', 'rps', 'must']);
  });

  it('rest uses the gateway path by default', () => {
    const card = cardFromForm({ ...emptyForm(), accessType: 'rest' }, defaults);
    expect(card.access.type).toBe('rest');
    expect(card.access.url).toBe('/v1/models/sys-001-cv-ranker/predict');
  });

  it('flags a bad URI, an inline secret and a negative limit', () => {
    const d = formFromCard(defaults);
    expect(validateForm(emptyForm(), d)).toEqual({});
    const bad = validateForm({ ...emptyForm(), uri: 's3://x', secretRef: 'abc123', rps: '-1' }, d);
    expect(Object.keys(bad).sort()).toEqual(['rps', 'secretRef', 'uri']);
  });
});
