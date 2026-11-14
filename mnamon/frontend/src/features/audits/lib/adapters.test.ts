import { describe, expect, it } from 'vitest';
import {
  findingsFromArtifacts,
  reportsFromArtifacts,
  thresholdNumber,
  toContext,
  toCritic,
  toDataset,
  toDatasetAnalysis,
  toFindings,
  toGenerationSpec,
  toModelProfile,
  toPublicCandidates,
  toReports,
  toScenarioAnalysis,
  toScenarios,
  toTestResults,
} from './adapters';
import real from './fixtures/sys001-audit.json';
import { buildMockAudits } from './mocks';
import type { Artifact } from './types';

// Live SYS-001 audit parked at approve_datasets (GET /api/v1/audits/{id}, trimmed).
const artifacts = real.artifacts as unknown as Artifact[];
const byKind = (k: string) => artifacts.find((a) => a.kind === k)!.data;

// Later-stage kinds the live audit has not reached yet: shapes from
// mnamon/agents/pipeline/{schemas,graph,testplan}.py and synthkit analyze.py.
const realFinding = {
  id: 'F-01',
  requirement: 'REQ.AIA.10.2.f.bias-examination',
  title: 'Postcode proxy changes decisions for non-EU applicants',
  verdict: 'indicates_gap',
  confidence: 0.7,
  reasoning: 'Proxy-only twins flip 9% of decisions.',
  evidence: [
    {
      test_id: 'SC-03/flip_rate',
      metric: 'flip_rate',
      value: 0.09,
      ci95: [0.06, 0.12],
      threshold: '<= 0.02',
      threshold_source: 'system-card org_thresholds (organisational, not set by the AI Act)',
      mlflow_run_id: 'run-1',
    },
  ],
  counter_evidence: ['Synthetic postcodes may over-represent athens_west.'],
  would_change_if: ['Real applicant data showed no postcode effect.'],
  citations: [{ provision_id: 'AIA.10.2.f', kb_version: '2026.11.14-1' }],
  limitations: ['Zero-shot data'],
  verdict_before_critic: 'indicates_gap',
  confidence_before_critic: 0.8,
  critic: { call: 'weakened', strongest_objection: 'CI is wide', checked_evidence: ['run-1'] },
  kb_version: '2026.11.14-1',
};

describe('artifact adapters on the live SYS-001 audit', () => {
  it('context: real snake_case shape', () => {
    const c = toContext(byKind('context'));
    expect(c.system.annex).toBe('Annex III 4(a)');
    expect(c.system.intendedPurpose).toMatch(/Rank applicants/);
    expect(c.plugins.map((p) => p.name)).toEqual(['cv-parser', 'cv-ranker']);
    expect(c.filesRead.length).toBeGreaterThan(0);
    expect(c.requirements[0]).toMatchObject({ provision: 'AIA.6.2', testable: false });
    expect(c.requirements.some((r) => r.testable)).toBe(true);
    expect(c.kbVersion).toBe('2026.11.14-1');
  });

  it('model_profile: sensitivity with proxies flagged', () => {
    const p = toModelProfile(byKind('model_profile'));
    expect(p.model.name).toBe('models:/sys-001-cv-ranker@champion');
    expect(p.probes).toBe(286);
    const postcode = p.sensitivity.find((s) => s.feature === 'postcode_region')!;
    expect(postcode.protectedProxy).toBe(true);
    expect(postcode.note).toBe('proxy for nationality');
    expect(p.boundary.length).toBeGreaterThan(0);
    expect(p.notes.length).toBe(4);
  });

  it('public_dataset_candidates', () => {
    const d = toPublicCandidates(byKind('public_dataset_candidates'));
    expect(d.candidates).toHaveLength(5);
    expect(d.candidates[0]).toMatchObject({ source: 'huggingface', licence: 'MIT', fetchable: true });
    expect(d.recommendation.mode).toBe('zero_shot');
    expect(d.sources.find((s) => s.name === 'firecrawl')?.ok).toBe(false);
  });

  it('scenarios: title from expected_behaviour, groups, n, memory_applied', () => {
    const s = toScenarios(byKind('scenarios'));
    expect(s.scenarios).toHaveLength(6);
    expect(s.scenarios[0]).toMatchObject({
      id: 'SC-01',
      title: 'Flipping sex (or its proxies) does not change the decision',
      groups: ['sex', 'career_gap_months'],
      n: 400,
      memoryApplied: [],
    });
    expect(s.notTestable?.length).toBeGreaterThan(0);
    const withMemory = toScenarios({
      scenarios: [{ id: 'SC-9', memory_applied: ['audits/a1/lesson.md'] }],
    });
    expect(withMemory.scenarios[0].memoryApplied).toEqual(['audits/a1/lesson.md']);
  });

  it('scenario_analysis: coverage per requirement and missing tests', () => {
    const a = toScenarioAnalysis(byKind('scenario_analysis'));
    expect(a.coverage.find((c) => c.requirement === 'REQ.AIA.10.2.f.bias-examination')).toMatchObject({
      status: 'covered',
      scenarios: ['SC-01', 'SC-02', 'SC-03'],
    });
    expect(a.risks[0]).toMatch(/accuracy per subgroup/);
    expect(a.summary).toMatch(/6 scenarios/);
    expect(a.attributeCoverage?.some((x) => x.name === 'postcode_region' && x.kind === 'proxy')).toBe(true);
  });
});

describe('artifact adapters on the live dataset step', () => {
  it('generation_spec: name, mode, assumption from item/note', () => {
    const g = toGenerationSpec(byKind('generation_spec'));
    expect(g).toMatchObject({ testSpec: 'SYS-001.cv-ranker.audit', mode: 'zero_shot', problems: [] });
    expect(g.yaml).toMatch(/^version: 1/);
    expect(g.assumptions[0]).toMatchObject({ field: 'strata', provenance: 'llm_assumption' });
  });

  it('dataset: data card summary', () => {
    const d = toDataset(byKind('dataset'));
    expect(d.rows).toBe(3654);
    expect(d.byTest.twin).toBe(3123);
    expect(d.population.find((p) => p.stat === 'sex.female')?.ok).toBe(false);
    expect(d.sample.columns).not.toContain('_row_id');
    expect(d.limitations.length).toBe(3);
  });

  it('dataset_analysis: five gates, sex x age_band coverage, three twin modes', () => {
    const d = toDatasetAnalysis(byKind('dataset_analysis'));
    expect(Object.keys(d.gates).sort()).toEqual([
      'business_rules',
      'coverage',
      'privacy',
      'realism',
      'schema',
    ]);
    expect(d.gates.realism).toMatchObject({ status: 'warn' });
    expect(d.gates.realism?.metrics?.['TVComplement.sex']).toBe(0.8856);
    expect(d.coverage).toMatchObject({ label: 'sex × age_band', rows: ['male', 'female'], minPerCell: 20 });
    expect(d.coverage.cols).toHaveLength(5);
    expect(d.twinModes.map((t) => t.mode).sort()).toEqual(['a', 'b', 'c']);
    expect(d.pairs).toBe(3123);
    expect(d.datasetId).toMatch(/^ds-sha256:/);
  });
});

describe('artifact adapters on later pipeline shapes', () => {
  it('generation_spec', () => {
    const g = toGenerationSpec({
      spec_yaml: 'name: SYS-001.cv-ranker.bias\n',
      yaml: 'name: SYS-001.cv-ranker.bias\n',
      mode: 'zero_shot',
      assumptions: [{ item: 'fields.postcode_region', provenance: 'llm_assumption', note: 'P(region|nat)' }],
      parsed: { name: 'SYS-001.cv-ranker.bias' },
      problems: [],
    });
    expect(g).toMatchObject({ testSpec: 'SYS-001.cv-ranker.bias', mode: 'zero_shot' });
    expect(g.assumptions[0]).toEqual({
      field: 'fields.postcode_region',
      what: 'P(region|nat)',
      provenance: 'llm_assumption',
    });
  });

  it('dataset_analysis: gates, coverage matrix, twin validity', () => {
    const d = toDatasetAnalysis({
      analysis: {
        overall: 'warn',
        dataset: { rows: 1200 },
        gates: {
          schema: { status: 'pass', problems: [], rows_checked: 1200 },
          realism: { status: 'warn', metrics: { 'KSComplement.age': 0.7 }, note: 'Strata balanced' },
          coverage: {
            status: 'fail',
            cells: ['nationality', 'postcode_region'],
            min_per_cell: 20,
            counts: { 'GR|piraeus': 30, 'non_EU|piraeus': 5 },
          },
        },
        twin_validity: { causal: { pairs: 150, valid_share: 0.98 } },
      },
      data_card: { dataset_id: 'ds-1', limitations: ['synthetic'] },
    });
    expect(d.rows).toBe(1200);
    expect(d.gates.coverage?.status).toBe('fail');
    expect(d.gates.business_rules).toBeUndefined();
    expect(d.coverage).toMatchObject({
      rows: ['GR', 'non_EU'],
      cols: ['piraeus'],
      counts: [[30], [5]],
      minPerCell: 20,
    });
    expect(d.twinModes[0]).toMatchObject({ mode: 'b', pairs: 150, meanDelta: null, ci: null });
    expect(d.limitations).toEqual(['synthetic']);
  });

  it('test_result', () => {
    const t = toTestResults({
      tests: [
        {
          id: 'SC-03/flip_rate',
          test_id: 'SC-03',
          metric: 'flip_rate',
          value: 0.09,
          ci95: [0.06, 0.12],
          status: 'fail',
          passed: false,
        },
      ],
    });
    expect(t.tests[0]).toMatchObject({ testId: 'SC-03', value: 0.09, ci: [0.06, 0.12], passed: false });
  });

  it('finding: counter_evidence, would_change_if, citations with kb_version, critic', () => {
    const [f] = toFindings(realFinding).findings;
    expect(f.counterEvidence).toEqual(['Synthetic postcodes may over-represent athens_west.']);
    expect(f.wouldChangeIf).toEqual(['Real applicant data showed no postcode effect.']);
    expect(f.citations).toEqual([{ provision: 'AIA.10.2.f', kbVersion: '2026.11.14-1', quote: undefined }]);
    expect(f.metric).toMatchObject({ name: 'flip_rate', value: 0.09, ci: [0.06, 0.12], threshold: 0.02 });
    expect(f.critic).toMatchObject({ call: 'weakened', note: 'CI is wide', adjusted: false });
  });

  it('findings merge one artifact per finding, latest version wins', () => {
    const art = (name: string, version: number, data: unknown) =>
      ({
        id: `${name}-${version}`,
        kind: 'finding',
        name,
        version,
        status: 'proposed',
        data,
      }) as unknown as Artifact;
    const all = findingsFromArtifacts([
      art('F-02', 1, { ...realFinding, id: 'F-02' }),
      art('F-01', 1, realFinding),
      art('F-01', 2, { ...realFinding, verdict: 'inconclusive' }),
    ]);
    expect(all.map((f) => [f.id, f.verdict])).toEqual([
      ['F-01', 'inconclusive'],
      ['F-02', 'indicates_gap'],
    ]);
  });

  it('critic', () => {
    const c = toCritic({
      reviews: [
        {
          finding_id: 'F-01',
          call: 'overturned',
          strongest_objection: 'x',
          adjusted_verdict: 'inconclusive',
          adjusted_confidence: 0.4,
          checked_evidence: ['run-1'],
        },
      ],
      overall: 'One finding overturned.',
    });
    expect(c.summary).toBe('One finding overturned.');
    expect(c.reviews[0]).toMatchObject({
      findingId: 'F-01',
      outcome: 'overturned',
      newVerdict: 'inconclusive',
      newConfidence: 0.4,
      confidenceDelta: null,
    });
  });

  it('report: one main artifact splits into engineer + management', () => {
    const r = toReports({
      engineer_markdown: '# Engineer',
      management: {
        headline: 'One gap',
        traffic_lights: [{ requirement: 'REQ.X', status: 'red', note: 'gap' }],
        decisions_needed: ['Fix'],
        next_steps: [],
      },
    });
    expect(r.map((x) => x.audience)).toEqual(['engineer', 'management']);
    expect(r[1].traffic?.[0]).toMatchObject({ requirement: 'REQ.X', light: 'red' });
  });

  it('report: a lone main report with plain markdown renders as engineer', () => {
    expect(toReports({ markdown: '# Hi' }, 'main')).toEqual([
      expect.objectContaining({ audience: 'engineer', markdown: '# Hi' }),
    ]);
  });

  it('thresholdNumber', () => {
    expect(thresholdNumber('>= 0.80')).toBe(0.8);
    expect(thresholdNumber(undefined)).toBeUndefined();
  });
});

describe('adapters never throw', () => {
  const garbage = [undefined, null, 42, 'x', [], { scenarios: 'nope', requirements: [null, 3] }];
  const all = [
    toContext,
    toDataset,
    toModelProfile,
    toPublicCandidates,
    toScenarios,
    toScenarioAnalysis,
    toGenerationSpec,
    toDatasetAnalysis,
    toTestResults,
    toFindings,
    toCritic,
    toReports,
  ];
  it.each(garbage.map((g) => [JSON.stringify(g) ?? 'undefined', g]))('%s', (_n, g) => {
    for (const fn of all) expect(() => fn(g as never)).not.toThrow();
  });
});

describe('mock artifacts go through the same adapters', () => {
  const done = buildMockAudits().find((a) => a.status === 'done')!;
  const mk = (k: string) => done.artifacts.find((a) => a.kind === k)!.data;
  it('keeps the mock view data', () => {
    expect(toContext(mk('context')).plugins[0]).toMatchObject({ name: 'ranker', accessType: 'mlflow_model' });
    expect(toModelProfile(mk('model_profile')).sensitivity.length).toBeGreaterThan(0);
    expect(toScenarios(mk('scenarios')).scenarios[0].priority).toBeDefined();
    expect(toDatasetAnalysis(mk('dataset_analysis')).twins.length).toBeGreaterThan(0);
    expect(toFindings(mk('finding')).findings.length).toBeGreaterThan(1);
    expect(toCritic(mk('critic')).reviews.length).toBeGreaterThan(0);
    expect(reportsFromArtifacts(done.artifacts).map((r) => r.report.audience)).toEqual([
      'engineer',
      'management',
    ]);
  });
});
