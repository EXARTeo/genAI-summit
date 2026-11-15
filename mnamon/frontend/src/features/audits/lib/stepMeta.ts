// What each pipeline step looks like on the graph and the stepper: its icon, a short hint
// while it has not run, and a one-line summary of what it produced (from its artifacts).
import {
  BarChart3,
  BookOpenCheck,
  Database,
  FileCode2,
  FileText,
  FlaskConical,
  Gauge,
  Hand,
  Lock,
  Pin,
  Scale,
  Layers,
  ListChecks,
  Microscope,
  ScanSearch,
  Swords,
  type LucideIcon,
} from 'lucide-react';
import {
  findingsFromArtifacts,
  reportsFromArtifacts,
  reviewedScenarios,
  toContext,
  toCritic,
  toDataset,
  toDatasetAnalysis,
  toGenerationSpec,
  toModelProfile,
  toPublicCandidates,
  toScenarioAnalysis,
  toScenarios,
  toTestResults,
} from './adapters';
import { latestByKind } from './pipeline';
import type { AuditDetail } from './types';

export const STEP_ICON: Record<string, LucideIcon> = {
  load_context: BookOpenCheck,
  pin: Pin,
  ground_obligations: Scale,
  profile_model: Gauge,
  plan_scenarios: ListChecks,
  analyse_scenarios: ScanSearch,
  approve_scenarios: Hand,
  find_public_data: Database,
  draft_spec: FileCode2,
  generate_data: Layers,
  analyse_datasets: BarChart3,
  approve_datasets: Hand,
  run_inference: FlaskConical,
  analyse_results: Microscope,
  assess_obligations: Scale,
  critic: Swords,
  seal: Lock,
  report: FileText,
};

/** Shown before a step has produced anything. */
export const STEP_HINT: Record<string, string> = {
  load_context: 'System card, plugins, requirements',
  pin: 'Model, regulation and data versions',
  ground_obligations: 'Obligations that apply to this system',
  profile_model: 'Sensitivity and decision boundaries',
  plan_scenarios: 'Requirements to test scenarios',
  analyse_scenarios: 'Coverage check and relevance review',
  approve_scenarios: 'You approve the test plan',
  find_public_data: 'Reference data for the scenarios',
  draft_spec: 'GenerationSpec with provenance',
  generate_data: 'Synthetic rows and twins',
  analyse_datasets: 'Five quality gates',
  approve_datasets: 'You approve the synthetic data',
  run_inference: 'The pinned model scores the data',
  analyse_results: 'Metrics computed in the sandbox',
  assess_obligations: 'A verdict per obligation',
  critic: 'Tries to overturn each finding',
  seal: 'Findings locked, read-only',
  report: 'Engineer and management reports',
};

const DECIDED: Record<string, string> = {
  approved: 'Approved',
  rejected: 'Rejected',
  changes_requested: 'Changes requested',
};

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

/** One line about what the step produced; undefined when it has nothing yet. */
export function stepSummary(stageId: string, audit: AuditDetail): string | undefined {
  const by = latestByKind(audit.artifacts);
  const data = (kind: string) => by[kind]?.[0]?.data;
  const decision = (gate: string) => {
    const d = [...audit.approvals].reverse().find((p) => p.gate === gate)?.decision;
    return d ? (DECIDED[d] ?? d.replace(/_/g, ' ')) : undefined;
  };
  switch (stageId) {
    case 'load_context': {
      if (!data('context')) return undefined;
      const c = toContext(data('context'));
      const testable = c.requirements.filter((r) => r.testable).length;
      return `${plural(c.requirements.length, 'requirement')} · ${testable} testable`;
    }
    case 'profile_model': {
      if (!data('model_profile')) return undefined;
      const p = toModelProfile(data('model_profile'));
      const proxies = p.sensitivity.filter((s) => s.protectedProxy).length;
      return [p.probes != null && `${p.probes.toLocaleString()} probes`, proxies && plural(proxies, 'proxy')]
        .filter(Boolean)
        .join(' · ')
        .replace('proxys', 'proxies');
    }
    case 'plan_scenarios': {
      if (!data('scenarios')) return undefined;
      const s = toScenarios(data('scenarios'));
      const flagged = reviewedScenarios(s).filter((x) => x.review.verdict !== 'relevant').length;
      return `${plural(s.scenarios.length, 'scenario')}${flagged ? ` · ${flagged} flagged in review` : ''}`;
    }
    case 'analyse_scenarios': {
      if (!data('scenario_analysis')) return undefined;
      const a = toScenarioAnalysis(data('scenario_analysis'));
      const gaps = a.risks.length;
      return `${plural(a.coverage.length, 'requirement')} covered${gaps ? ` · ${plural(gaps, 'gap')}` : ''}`;
    }
    case 'approve_scenarios':
      return decision('scenarios');
    case 'find_public_data': {
      if (!data('public_dataset_candidates')) return undefined;
      const c = toPublicCandidates(data('public_dataset_candidates'));
      const picked = decision('public_data');
      return `${plural(c.candidates.length, 'candidate')}${picked ? ` · ${picked}` : ''}`;
    }
    case 'draft_spec': {
      if (!data('generation_spec')) return undefined;
      const g = toGenerationSpec(data('generation_spec'));
      const llm = g.assumptions.filter((a) => a.provenance === 'llm_assumption').length;
      return [g.mode?.replace(/_/g, '-'), llm && `${llm} to check`].filter(Boolean).join(' · ');
    }
    case 'generate_data': {
      if (!data('dataset')) return undefined;
      const d = toDataset(data('dataset'));
      const twins = Object.values(d.twinsByMode).reduce((a, b) => a + b, 0);
      return [d.rows != null && `${d.rows.toLocaleString()} rows`, twins && `${twins.toLocaleString()} twins`]
        .filter(Boolean)
        .join(' · ');
    }
    case 'analyse_datasets': {
      if (!data('dataset_analysis')) return undefined;
      const d = toDatasetAnalysis(data('dataset_analysis'));
      const gates = Object.values(d.gates);
      const pass = gates.filter((g) => g?.status === 'pass').length;
      const warn = gates.filter((g) => g?.status === 'warn').length;
      const fail = gates.filter((g) => g?.status === 'fail').length;
      return [`${pass}/${gates.length || 5} gates pass`, warn && `${warn} warn`, fail && `${fail} fail`]
        .filter(Boolean)
        .join(' · ');
    }
    case 'approve_datasets':
      return decision('datasets');
    case 'pin': {
      const p = data('pins') as { model_version?: string; kb_version?: string } | undefined;
      if (!p) return undefined;
      return [p.model_version && `model v${p.model_version}`, p.kb_version && `kb ${p.kb_version}`]
        .filter(Boolean)
        .join(' · ');
    }
    case 'ground_obligations': {
      const yaml = (data('obligation_map') as { yaml?: string } | undefined)?.yaml;
      if (typeof yaml !== 'string') return undefined;
      const total = (yaml.match(/obligation_id:/g) ?? []).length;
      const applicable = (yaml.match(/applicable: true/g) ?? []).length;
      return `${plural(total, 'obligation')} · ${applicable} apply`;
    }
    case 'run_inference': {
      const run = (data('inference') as { run?: { model?: { stats?: { rows?: number; errors?: number } } } })
        ?.run;
      const stats = run?.model?.stats;
      if (stats?.rows != null)
        return `${stats.rows.toLocaleString()} predictions${stats.errors ? ` · ${stats.errors} errors` : ''}`;
      if (!data('test_result')) return undefined;
      const t = toTestResults(data('test_result'));
      if (t.summary) return `${t.summary.runs ?? 0} runs · ${t.summary.failed ?? 0} failed`;
      const failed = t.tests.filter((x) => x.passed === false).length;
      return `${plural(t.tests.length, 'test')}${failed ? ` · ${failed} failed` : ''}`;
    }
    case 'analyse_results': {
      const code = (data('analysis') as { code?: unknown[] } | undefined)?.code;
      return Array.isArray(code) ? `${plural(code.length, 'code run')} in the sandbox` : undefined;
    }
    case 'assess_obligations': {
      const f = findingsFromArtifacts(audit.artifacts);
      if (!f.length) return undefined;
      const gaps = f.filter((x) => x.verdict === 'gap' || x.verdict === 'indicates_gap').length;
      // The UI copy of a finding labels both gap and partial as a gap ("indicates_gap").
      return `${plural(f.length, 'finding')}${gaps ? ` · ${gaps} gap or partial` : ''}`;
    }
    case 'critic': {
      if (!data('critic')) return undefined;
      const c = toCritic(data('critic'));
      const changed = c.reviews.filter((r) => r.outcome !== 'upheld').length;
      return `${plural(c.reviews.length, 'review')}${changed ? ` · ${changed} changed` : ''}`;
    }
    case 'seal': {
      const seal = data('seal') as { count?: number; head_hash?: string; gaps?: unknown[] } | undefined;
      if (!seal) return undefined;
      const n = seal.count ?? (Array.isArray(seal.gaps) ? seal.gaps.length : undefined);
      return [n != null && `${n} sealed`, seal.head_hash && `chain ${seal.head_hash.slice(0, 8)}`]
        .filter(Boolean)
        .join(' · ');
    }
    case 'report': {
      const r = reportsFromArtifacts(audit.artifacts);
      if (!r.length) return undefined;
      return r.map((x) => (x.report.audience === 'engineer' ? 'Engineer' : 'Management')).join(' + ');
    }
    default:
      return undefined;
  }
}
