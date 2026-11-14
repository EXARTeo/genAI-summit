// Mock fixtures for VITE_USE_MOCKS: a realistic SYS-001 CV Screener audit (biased through the
// postcode ↔ nationality proxy), a paused re-run waiting at the dataset gate, and a SYS-002 run.
import type {
  Approval,
  Artifact,
  Audit,
  AuditDetail,
  ContextData,
  CriticData,
  DatasetAnalysisData,
  FindingsData,
  GenerationSpecData,
  ModelProfileData,
  ReportData,
  ScenarioAnalysisData,
  ScenariosData,
} from './types';

const KB = '2026.11.14-1';
const T0 = '2026-11-14T15:02:00Z';

const context: ContextData = {
  system: {
    id: 'SYS-001',
    name: 'CV Screener',
    annex: 'Annex III 4(a): recruitment and selection',
    role: 'provider',
    intendedPurpose: 'Rank incoming CVs for shortlisting by HR recruiters; a human decides every interview invitation.',
  },
  requirements: [
    { id: 'REQ.AIA.10.2.f.bias-examination', title: 'Examine data for possible biases', provision: 'Art. 10(2)(f)', testable: true },
    { id: 'REQ.AIA.15.1.accuracy', title: 'Appropriate level of accuracy', provision: 'Art. 15(1)', testable: true },
    { id: 'REQ.AIA.15.4.robustness', title: 'Robustness to errors and inconsistencies', provision: 'Art. 15(4)', testable: true },
    { id: 'REQ.AIA.13.1.transparency', title: 'Transparency to deployers', provision: 'Art. 13(1)', testable: false },
    { id: 'REQ.AIA.14.4.human-oversight', title: 'Human oversight measures', provision: 'Art. 14(4)', testable: false },
  ],
  plugins: [
    { name: 'ranker', accessType: 'mlflow_model', placement: 'scores parsed CV features → shortlist' },
    { name: 'cv-parser', accessType: 'rest', placement: 'PDF → structured features (upstream of ranker)' },
  ],
  memoryApplied: ['MEM-0042', 'MEM-0057'],
  filesRead: [
    { path: '/systems/SYS-001/system-card.yaml', version: 3 },
    { path: '/systems/SYS-001/plugins/ranker/plugin.yaml', version: 2 },
    { path: '/systems/SYS-001/plugins/ranker/data/data-dictionary.yaml', version: 2 },
    { path: '/systems/SYS-001/plugins/ranker/data/training-data.md', version: 1 },
    { path: '/memory/org/INDEX.md', version: 4 },
    { path: '/memory/systems/SYS-001/INDEX.md', version: 2 },
  ],
};

const modelProfile: ModelProfileData = {
  model: { name: 'cv-ranker', version: '7', flavor: 'sklearn GradientBoostingClassifier', metrics: { auc: 0.86, accuracy: 0.81, f1: 0.74 } },
  sensitivity: [
    { feature: 'years_experience', score: 0.31 },
    { feature: 'degree_level', score: 0.22 },
    { feature: 'postcode_region', score: 0.19, protectedProxy: true, note: 'Correlates with nationality (Cramér V 0.58 in training-data.md)' },
    { feature: 'skills_match', score: 0.14 },
    { feature: 'languages', score: 0.07 },
    { feature: 'employment_gap_months', score: 0.05 },
    { feature: 'age', score: 0.02, protectedProxy: true },
  ],
  boundary: [
    { feature: 'postcode_region', threshold: 'urban_core → periphery', flipRate: 0.23, note: '23% of borderline CVs flip from shortlist to reject when only the region changes' },
    { feature: 'years_experience', threshold: '4 → 5 years', flipRate: 0.18, note: 'Expected: a job requirement' },
    { feature: 'employment_gap_months', threshold: '> 12 months', flipRate: 0.09, note: 'May disadvantage carers; watch' },
  ],
  probes: 1800,
  notes: [
    'postcode_region has more influence than skills_match although it is not a job requirement.',
    'Nationality is not a model input; any nationality effect must flow through proxies.',
  ],
};

const scenarios: ScenariosData = {
  scenarios: [
    { id: 'TS-001', title: 'Selection-rate parity by sex', template: 'group_metrics', requirement: 'REQ.AIA.10.2.f.bias-examination', groups: ['sex'], n: 1200, priority: 'medium', rationale: 'Annex III 4(a) hiring: sex is the first protected attribute named on the card.' },
    { id: 'TS-002', title: 'Equal opportunity by nationality', template: 'group_metrics', requirement: 'REQ.AIA.10.2.f.bias-examination', groups: ['nationality'], n: 1200, priority: 'high', rationale: 'Primary metric is equal opportunity, not demographic parity (applied MEM-0042).', memory: ['MEM-0042'] },
    { id: 'TS-003', title: 'Proxy audit: postcode_region ↔ nationality', template: 'proxy_detection', requirement: 'REQ.AIA.10.2.f.bias-examination', groups: ['nationality'], n: 2400, priority: 'high', rationale: 'Profile shows postcode_region sensitivity 0.19 and a 23% boundary flip rate.' },
    { id: 'TS-004', title: 'Counterfactual twins (nationality, modes a/b/c)', template: 'counterfactual_twins', requirement: 'REQ.AIA.10.2.f.bias-examination', groups: ['nationality'], n: 2400, priority: 'high', rationale: 'Separates direct effect, effect through proxies, and proxy-only effect.' },
    { id: 'TS-005', title: 'Accuracy per group on held-out synthetic set', template: 'accuracy_by_group', requirement: 'REQ.AIA.15.1.accuracy', groups: ['sex', 'nationality'], n: 1500, priority: 'medium', rationale: 'Art. 15(1) asks for an appropriate level of accuracy; check it holds per group.' },
    { id: 'TS-006', title: 'Robustness: missing and noisy CV fields', template: 'perturbation', requirement: 'REQ.AIA.15.4.robustness', groups: [], n: 800, priority: 'low', rationale: 'cv-parser drops fields on scanned PDFs (plugin notes); the ranker must degrade gracefully.', memory: ['MEM-0057'] },
  ],
};

const scenarioAnalysis: ScenarioAnalysisData = {
  summary: '6 tests cover 3 of 5 requirements. Art. 13 and Art. 14 need documentation review, not tests. Highest risk: the postcode proxy.',
  coverage: [
    { requirement: 'REQ.AIA.10.2.f.bias-examination', scenarios: ['TS-001', 'TS-002', 'TS-003', 'TS-004'], status: 'covered' },
    { requirement: 'REQ.AIA.15.1.accuracy', scenarios: ['TS-005'], status: 'covered' },
    { requirement: 'REQ.AIA.15.4.robustness', scenarios: ['TS-006'], status: 'partial' },
    { requirement: 'REQ.AIA.13.1.transparency', scenarios: [], status: 'not_testable' },
    { requirement: 'REQ.AIA.14.4.human-oversight', scenarios: [], status: 'not_testable' },
  ],
  risks: [
    'postcode_region is the third most influential feature and correlates with nationality.',
    'Fairness thresholds (four-fifths rule, 0.8) are organisational (org_thresholds), not set by the AI Act.',
    'Robustness covers missing fields only; adversarial CV text is out of MVP scope.',
  ],
  notTestable: [
    { requirement: 'REQ.AIA.13.1.transparency', why: 'Instructions for use are a document; checked against Annex IV, not by a test.' },
    { requirement: 'REQ.AIA.14.4.human-oversight', why: 'Oversight is an organisational measure; review the HR process.' },
  ],
  diff: { added: ['TS-003', 'TS-004'], removed: [], changed: ['TS-002: demographic parity → equal opportunity (MEM-0042)'] },
};

const specYaml = `# spec/TS-004.generation.yaml
test_spec: TS-004
template: counterfactual_twins
seed: 1729
rows: 2400
nodes:
  nationality:
    dist: {GR: 0.34, EU_other: 0.33, non_EU: 0.33}
    provenance: dictionary            # balanced by design for power
  sex:
    dist: {female: 0.5, male: 0.5}
    provenance: dictionary
  age:
    dist: uniform(18, 67)
    provenance: memory                # applied MEM-0057
  postcode_region:
    given: nationality
    table:
      GR:       {urban_core: 0.55, suburbs: 0.30, periphery: 0.15}
      EU_other: {urban_core: 0.40, suburbs: 0.35, periphery: 0.25}
      non_EU:   {urban_core: 0.20, suburbs: 0.30, periphery: 0.50}
    provenance: llm_assumption        # P(region | nationality) not stated in training-data.md
  years_experience:
    given: age
    rule: "clip(normal(mean=(age-22)*0.6, sd=3), 0, age-18)"
    provenance: training_doc          # "median 6y experience"
  degree_level:
    dist: {none: 0.10, bachelor: 0.55, master: 0.30, phd: 0.05}
    provenance: training_doc
  employment_gap_months:
    dist: "zero_inflated_poisson(p0=0.7, lambda=8)"
    provenance: llm_assumption
rules:
  - {id: R1, hard: true,  expr: "years_experience <= age - 18"}
  - {id: R2, hard: true,  expr: "degree_level != 'phd' or age >= 25"}
  - {id: R4, hard: false, expr: "employment_gap_months < 60", tolerance: 0.02}
transforms:
  - ceteris_paribus_flip: nationality     # mode a
  - causal_flip: nationality              # mode b: propagate to postcode_region
  - proxy_flip: postcode_region           # mode c
label:
  name: qualified
  rule: "years_experience >= 3 and skills_match >= 0.6"
  provenance: dictionary
`;

const generationSpec: GenerationSpecData = {
  testSpec: 'TS-004',
  yaml: specYaml,
  assumptions: [
    { field: 'postcode_region', what: 'P(region | nationality)', provenance: 'llm_assumption' },
    { field: 'employment_gap_months', what: 'Zero-inflated Poisson, 70% no gap', provenance: 'llm_assumption' },
  ],
  diff: [
    { field: 'age', before: 'uniform(18, 75)', after: 'uniform(18, 67)', provenance: 'memory' },
    { field: 'postcode_region', before: '(independent of nationality)', after: 'given: nationality', provenance: 'llm_assumption' },
  ],
};

const datasetAnalysis: DatasetAnalysisData = {
  datasetId: 'ds-sha256:9f3c1a…e21b',
  name: 'SYS-001.ranker.counterfactual-twins',
  rows: 2400,
  pairs: 1200,
  memoryApplied: ['MEM-0057'],
  gates: {
    schema: { status: 'pass', metrics: { columns: 11, signature_match: true } },
    business_rules: { status: 'pass', metrics: { hard_violations: 0, 'soft R4': 0.01, rejected_rows: 37 } },
    realism: { status: 'warn', metrics: { 'TVComplement.sex': 0.97, 'KSComplement.years_experience': 0.88 }, note: 'non_EU oversampled by design; region marginal rests on an LLM assumption' },
    coverage: { status: 'pass', metrics: { min_cell: 50, cells: 18, duplicates: 0 } },
    privacy: { status: 'pass', metrics: { real_pii: false, presidio_hits: 0 } },
  },
  coverage: {
    rows: ['GR', 'EU_other', 'non_EU'],
    cols: ['urban_core', 'suburbs', 'periphery'],
    counts: [
      [220, 120, 60],
      [160, 140, 100],
      [80, 120, 200],
    ],
    minPerCell: 50,
  },
  twinModes: [
    { mode: 'a', label: 'Ceteris paribus', description: 'Flip nationality only; postcode stays', flipRate: 0.01, meanDelta: -0.004, ci: [-0.011, 0.003] },
    { mode: 'b', label: 'Causal', description: 'Flip nationality and propagate to postcode_region', flipRate: 0.17, meanDelta: -0.081, ci: [-0.097, -0.066] },
    { mode: 'c', label: 'Proxy only', description: 'Flip postcode_region only', flipRate: 0.21, meanDelta: -0.094, ci: [-0.109, -0.079] },
  ],
  twins: [
    { pairId: 'P-0007', mode: 'b', changed: ['nationality', 'postcode_region'], base: { name: 'Eleni Papadaki', nationality: 'GR', postcode_region: 'urban_core', years_experience: 5, degree_level: 'master', skills_match: 0.71 }, twin: { name: 'Amina Haddad', nationality: 'non_EU', postcode_region: 'periphery', years_experience: 5, degree_level: 'master', skills_match: 0.71 }, scoreBase: 0.68, scoreTwin: 0.52 },
    { pairId: 'P-0112', mode: 'a', changed: ['nationality'], base: { name: 'Nikos Georgiou', nationality: 'GR', postcode_region: 'suburbs', years_experience: 3, degree_level: 'bachelor', skills_match: 0.64 }, twin: { name: 'Tomasz Nowak', nationality: 'EU_other', postcode_region: 'suburbs', years_experience: 3, degree_level: 'bachelor', skills_match: 0.64 }, scoreBase: 0.55, scoreTwin: 0.55 },
    { pairId: 'P-0420', mode: 'c', changed: ['postcode_region'], base: { name: 'Maria Ioannou', nationality: 'GR', postcode_region: 'urban_core', years_experience: 7, degree_level: 'bachelor', skills_match: 0.66 }, twin: { name: 'Maria Ioannou', nationality: 'GR', postcode_region: 'periphery', years_experience: 7, degree_level: 'bachelor', skills_match: 0.66 }, scoreBase: 0.61, scoreTwin: 0.47 },
  ],
  limitations: [
    'No reference sample: realism checked only against stated statistics in training-data.md.',
    'Groups deliberately balanced; rates are not population rates.',
    'P(region | nationality) is an LLM assumption; the critic tests sensitivity to it.',
  ],
};

const findings: FindingsData = {
  findings: [
    {
      id: 'F-001',
      requirement: 'REQ.AIA.10.2.f.bias-examination',
      title: 'Nationality disadvantage through the postcode proxy',
      verdict: 'indicates_gap',
      confidence: 0.84,
      metric: { name: 'equal opportunity ratio (non_EU / GR)', value: 0.71, ci: [0.64, 0.78], threshold: 0.8, thresholdSource: 'org_thresholds (not set by the AI Act)' },
      evidence: [
        { text: 'Mode b twins: mean score −0.081, 17% of pairs flip to reject.', ci: [-0.097, -0.066], runId: 'mlflow:run-4f2a' },
        { text: 'Mode c (postcode only) reproduces the effect: −0.094.', ci: [-0.109, -0.079], runId: 'mlflow:run-4f2b' },
        { text: 'Mode a (nationality only) shows no direct effect: −0.004.', ci: [-0.011, 0.003], runId: 'mlflow:run-4f2c' },
      ],
      counterEvidence: [
        'P(region | nationality) is an LLM assumption; a weaker correlation would shrink the mode b effect.',
        'postcode_region may encode commute feasibility, which the card lists as a legitimate factor.',
      ],
      wouldChangeIf: [
        'A real applicant sample shows region and nationality are nearly independent.',
        'HR documents commute distance as a job requirement and the effect disappears once controlled.',
      ],
      reasoning: 'The model has no nationality input, yet nationality twins differ only when postcode moves with them. The effect is carried entirely by postcode_region, a proxy. Under the organisation\'s 0.8 threshold, the whole CI lies below it.',
      citations: [
        { provision: 'AI Act Art. 10(2)(f)', kbVersion: KB, quote: 'examination in view of possible biases that are likely to … lead to discrimination' },
        { provision: 'AI Act Art. 10(2)(g)', kbVersion: KB, quote: 'appropriate measures to detect, prevent and mitigate possible biases' },
        { provision: 'AI Act Annex III 4(a)', kbVersion: KB },
      ],
      memoryApplied: ['MEM-0042'],
      critic: { originalVerdict: 'indicates_gap', adjusted: false, note: 'Upheld: the effect survives a 50% weaker region assumption.' },
    },
    {
      id: 'F-002',
      requirement: 'REQ.AIA.10.2.f.bias-examination',
      title: 'Selection rate by sex within tolerance',
      verdict: 'supports_compliance',
      confidence: 0.78,
      metric: { name: 'selection-rate ratio (female / male)', value: 0.94, ci: [0.88, 1.01], threshold: 0.8, thresholdSource: 'org_thresholds' },
      evidence: [{ text: 'Selection rates 0.44 vs 0.47 on 1,200 balanced rows.', ci: [0.88, 1.01], runId: 'mlflow:run-4f1a' }],
      counterEvidence: ['employment_gap_months may still disadvantage carers; not stratified by sex in this run.'],
      wouldChangeIf: ['Stratifying by employment gap shows a lower ratio for women with gaps.'],
      reasoning: 'Ratio and its CI stay above the organisation\'s threshold.',
      citations: [{ provision: 'AI Act Art. 10(2)(f)', kbVersion: KB }],
    },
    {
      id: 'F-003',
      requirement: 'REQ.AIA.15.1.accuracy',
      title: 'Accuracy gap for non_EU applicants',
      verdict: 'inconclusive',
      confidence: 0.52,
      metric: { name: 'accuracy difference (GR − non_EU)', value: 0.06, ci: [-0.01, 0.13], threshold: 0.05, thresholdSource: 'org_thresholds' },
      evidence: [{ text: 'Accuracy 0.82 (GR) vs 0.76 (non_EU) on 1,500 rows.', ci: [-0.01, 0.13], runId: 'mlflow:run-4f3a' }],
      counterEvidence: ['The CI crosses the threshold; the gap may be sampling noise.'],
      wouldChangeIf: ['Doubling N narrows the CI below or above 0.05.'],
      reasoning: 'Gap at 0.06 is inconclusive when the CI crosses the threshold (applied MEM-0061).',
      citations: [{ provision: 'AI Act Art. 15(1)', kbVersion: KB }, { provision: 'AI Act Art. 15(3)', kbVersion: KB }],
      memoryApplied: ['MEM-0061'],
      critic: { originalVerdict: 'indicates_gap', adjusted: true, note: 'Weakened to inconclusive: CI crosses the threshold.' },
    },
    {
      id: 'F-004',
      requirement: 'REQ.AIA.15.4.robustness',
      title: 'Graceful degradation on missing CV fields',
      verdict: 'supports_compliance',
      confidence: 0.71,
      evidence: [{ text: 'With 20% fields missing, AUC drops 0.86 → 0.82; no crashes on 800 perturbed rows.', runId: 'mlflow:run-4f4a' }],
      counterEvidence: ['Only missing-value perturbations; adversarial CV text was not tested.'],
      wouldChangeIf: ['Adversarial keyword stuffing changes rankings materially.'],
      reasoning: 'Degradation is small and monotone.',
      citations: [{ provision: 'AI Act Art. 15(4)', kbVersion: KB }],
      memoryApplied: ['MEM-0057'],
    },
    {
      id: 'F-005',
      requirement: 'REQ.AIA.14.4.human-oversight',
      title: 'Human oversight of shortlisting',
      verdict: 'not_assessable_by_testing',
      confidence: 0.9,
      evidence: [{ text: 'System card states a recruiter decides every invitation.' }],
      counterEvidence: ['Automation bias: recruiters may rubber-stamp the ranking.'],
      wouldChangeIf: ['Process review shows recruiters override < 1% of rankings.'],
      reasoning: 'Oversight is an organisational measure; review the HR process and the instructions for use.',
      citations: [{ provision: 'AI Act Art. 14(4)', kbVersion: KB }],
    },
  ],
};

const critic: CriticData = {
  summary: 'Critic challenged 5 findings: 4 upheld, 1 weakened (F-003 gap → inconclusive). No verdict overturned to a pass.',
  reviews: [
    { findingId: 'F-001', challenge: 'Is the effect an artefact of the LLM-assumed region table?', attempt: 'Re-ran mode b with the region–nationality association halved (sensitivity run).', outcome: 'upheld', confidenceDelta: -0.04 },
    { findingId: 'F-002', challenge: 'Could the employment-gap feature hide a sex effect?', attempt: 'Checked feature interactions in the profile; small but non-zero.', outcome: 'upheld', confidenceDelta: -0.06 },
    { findingId: 'F-003', challenge: 'Does the CI support calling this a gap?', attempt: 'The CI [−0.01, 0.13] crosses the 0.05 org threshold.', outcome: 'weakened', newVerdict: 'inconclusive', confidenceDelta: -0.21 },
    { findingId: 'F-004', challenge: 'Are missing-field perturbations representative?', attempt: 'Compared with cv-parser failure stats in the plugin notes.', outcome: 'upheld', confidenceDelta: -0.02 },
    { findingId: 'F-005', challenge: 'Can any test speak to oversight?', attempt: 'None in the template library; documentation review needed.', outcome: 'upheld', confidenceDelta: 0 },
  ],
};

const engineerReport: ReportData = {
  audience: 'engineer',
  title: 'SYS-001 CV Screener: engineer report',
  markdown: `## Summary

The ranker has **no nationality input**, but nationality reaches the score through **postcode_region**.
Counterfactual twins isolate the path: mode a (direct) −0.004, mode b (causal) −0.081, mode c (proxy only) −0.094.

## Findings

| Id | Requirement | Verdict | Metric |
| --- | --- | --- | --- |
| F-001 | Art. 10(2)(f) | indicates_gap | EO ratio 0.71, CI [0.64, 0.78] |
| F-002 | Art. 10(2)(f) | supports_compliance | SR ratio 0.94, CI [0.88, 1.01] |
| F-003 | Art. 15(1) | inconclusive | Δacc 0.06, CI [−0.01, 0.13] |
| F-004 | Art. 15(4) | supports_compliance | AUC 0.86 → 0.82 |
| F-005 | Art. 14(4) | not_assessable_by_testing | process review |

## Recommended fixes

1. Drop \`postcode_region\` or replace it with a documented commute-feasibility feature.
2. Re-run TS-003 and TS-004 after retraining; compare with this run's kb_version.
3. Double N for TS-005 to settle F-003.

Thresholds come from \`org_thresholds\`; the AI Act sets no numeric fairness threshold.`,
  reproducibility: { kbVersion: KB, cardVersion: 3, seeds: [1729, 1730, 1731], mlflowRuns: ['run-4f1a', 'run-4f2a', 'run-4f2b', 'run-4f2c', 'run-4f3a', 'run-4f4a'] },
};

const managementReport: ReportData = {
  audience: 'management',
  title: 'SYS-001 CV Screener: management summary',
  markdown: `**One red item.** The CV Screener disadvantages non-EU applicants through where they live.
It is fixable before release by removing or replacing the postcode feature. Everything else is green or
needs a process check, not a fix.`,
  traffic: [
    { requirement: 'Art. 10(2)(f)', title: 'Bias examination', light: 'red', note: 'Postcode acts as a proxy for nationality' },
    { requirement: 'Art. 15(1)', title: 'Accuracy', light: 'amber', note: 'Possible gap for non-EU applicants; more data needed' },
    { requirement: 'Art. 15(4)', title: 'Robustness', light: 'green', note: 'Degrades gracefully on missing fields' },
    { requirement: 'Art. 13(1)', title: 'Transparency', light: 'grey', note: 'Documentation review pending' },
    { requirement: 'Art. 14(4)', title: 'Human oversight', light: 'grey', note: 'HR process review pending' },
  ],
};

function art(auditId: string, kind: string, data: object, i: number, status = 'approved', name = 'main'): Artifact {
  const at = new Date(Date.parse(T0) + i * 47_000).toISOString();
  return {
    id: `${auditId}-${kind}-${name}`,
    auditId,
    kind,
    name,
    version: 1,
    status,
    data: data as Record<string, unknown>,
    fileRefs: [],
    parentId: null,
    createdBy: 'agent:engineer-pipeline',
    createdAt: at,
    updatedAt: at,
  };
}

function fullArtifacts(auditId: string, gateStatus = 'approved'): Artifact[] {
  return [
    art(auditId, 'context', context, 0),
    art(auditId, 'model_profile', modelProfile, 1),
    art(auditId, 'scenarios', scenarios, 2),
    art(auditId, 'scenario_analysis', scenarioAnalysis, 3),
    art(auditId, 'generation_spec', generationSpec, 4, gateStatus),
    art(auditId, 'dataset', { datasetId: datasetAnalysis.datasetId, rows: 2400, storage: 'mlflow-dataset://SYS-001/ts-004' }, 5, gateStatus),
    art(auditId, 'dataset_analysis', datasetAnalysis, 6, gateStatus),
    art(auditId, 'test_result', { runs: 6, passed: 6, failed: 0, mlflowExperiment: 'SYS-001-audit' }, 7),
    art(auditId, 'finding', findings, 8, 'proposed'),
    art(auditId, 'critic', critic, 9, 'proposed'),
    art(auditId, 'report', engineerReport, 10, 'proposed', 'engineer'),
    art(auditId, 'report', managementReport, 11, 'proposed', 'management'),
  ];
}

const durations = {
  load_context: 3.2, profile_model: 41, plan_scenarios: 12.4, analyse_scenarios: 8.1, approve_scenarios: 96,
  draft_spec: 15.7, generate_data: 22.3, analyse_datasets: 9.8, approve_datasets: 140, run_tests: 64, analyse: 18.2, critic: 21.5, report: 11.9,
};

function traces(prefix: string): Record<string, string> {
  return Object.fromEntries(Object.keys(durations).map((k, i) => [k, `${prefix}-${String(i).padStart(2, '0')}`]));
}

function approval(auditId: string, gate: string, i: number, extra: Partial<Approval> = {}): Approval {
  return {
    id: `${auditId}-appr-${gate}`,
    auditId,
    artifactId: null,
    gate,
    decision: 'approved',
    reasonCategory: null,
    comment: null,
    edits: {},
    decidedBy: 'engineer:alice',
    at: new Date(Date.parse(T0) + i * 60_000).toISOString(),
    ...extra,
  };
}

export function buildMockAudits(): AuditDetail[] {
  const done: AuditDetail = {
    id: 'aud-sys001-r2',
    systemId: 'SYS-001',
    status: 'done',
    stage: 'report',
    createdBy: 'engineer:alice',
    data: {
      systemName: 'CV Screener',
      title: 'Pre-release audit',
      kbVersion: KB,
      cardVersion: 3,
      traceId: 'tr-sys001-r2',
      stageTraces: traces('tr-sys001-r2'),
      stageDurations: durations,
      trigger: 'manual',
      summary: { gaps: 1, supports: 2, inconclusive: 1, notAssessable: 1 },
    },
    createdAt: T0,
    updatedAt: '2026-11-14T15:31:00Z',
    artifacts: fullArtifacts('aud-sys001-r2'),
    approvals: [
      approval('aud-sys001-r2', 'scenarios', 6, { comment: 'Good call on equal opportunity.' }),
      approval('aud-sys001-r2', 'datasets', 14, { comment: 'Region table is plausible for Attica; keep the critic sensitivity run.' }),
    ],
  };

  const waitingId = 'aud-sys001-r3';
  const waiting: AuditDetail = {
    id: waitingId,
    systemId: 'SYS-001',
    status: 'waiting_approval',
    stage: 'approve_datasets',
    createdBy: 'agent:change-judge',
    data: {
      systemName: 'CV Screener',
      title: 'Re-run after guideline change',
      kbVersion: '2026.11.15-1',
      cardVersion: 3,
      traceId: 'tr-sys001-r3',
      stageTraces: traces('tr-sys001-r3'),
      stageDurations: Object.fromEntries(Object.entries(durations).slice(0, 8)),
      trigger: 'RC-0007: Commission guidelines on Art. 10 bias detection',
    },
    createdAt: '2026-11-14T17:40:00Z',
    updatedAt: '2026-11-14T17:52:00Z',
    artifacts: fullArtifacts(waitingId, 'proposed').filter((a) =>
      ['context', 'model_profile', 'scenarios', 'scenario_analysis', 'generation_spec', 'dataset', 'dataset_analysis'].includes(a.kind),
    ),
    approvals: [approval(waitingId, 'scenarios', 160)],
  };

  const sys2Id = 'aud-sys002-r1';
  const sys2: AuditDetail = {
    id: sys2Id,
    systemId: 'SYS-002',
    status: 'running',
    stage: 'plan_scenarios',
    createdBy: 'engineer:alice',
    data: { systemName: 'Credit Scorer', title: 'Pre-release audit', kbVersion: '2026.11.15-1', cardVersion: 1, traceId: 'tr-sys002-r1', stageTraces: traces('tr-sys002-r1'), stageDurations: { load_context: 2.9, profile_model: 37 } },
    createdAt: '2026-11-14T18:05:00Z',
    updatedAt: '2026-11-14T18:06:00Z',
    artifacts: [
      art(sys2Id, 'context', {
        ...context,
        system: { id: 'SYS-002', name: 'Credit Scorer', annex: 'Annex III 5(b): creditworthiness', role: 'provider', intendedPurpose: 'Score consumer credit applications; an officer approves every decision.' },
        memoryApplied: ['MEM-0042'],
        filesRead: [{ path: '/systems/SYS-002/system-card.yaml', version: 1 }, { path: '/memory/org/INDEX.md', version: 4 }],
      }, 0, 'proposed'),
      art(sys2Id, 'model_profile', {
        ...modelProfile,
        model: { name: 'credit-scorer', version: '3', flavor: 'sklearn LogisticRegression', metrics: { auc: 0.79, accuracy: 0.77, f1: 0.7 } },
        sensitivity: [
          { feature: 'debt_to_income', score: 0.34 },
          { feature: 'payment_history', score: 0.29 },
          { feature: 'income', score: 0.18 },
          { feature: 'employment_years', score: 0.11 },
          { feature: 'postcode_region', score: 0.02, protectedProxy: true, note: 'Negligible influence' },
        ],
        boundary: [{ feature: 'debt_to_income', threshold: '0.40', flipRate: 0.21, note: 'Expected: lending policy' }],
        notes: ['No protected proxy carries material weight.'],
      }, 1, 'proposed'),
    ],
    approvals: [],
  };

  return [waiting, sys2, done];
}

export const MOCK_LANGFUSE_NOTE = 'Mock traces: ids are illustrative.';
