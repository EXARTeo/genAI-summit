// The audit report model (plan 01 §8): what the Report tab renders and exports as PDF.
// Sources, best first: the pipeline's report artifact(s), then values derived from the
// sealed findings (gap list, evidence register, traffic lights) so a report always renders.
import { reportsFromArtifacts } from './adapters';
import {
  articleOf,
  evidenceRegister,
  gapList,
  type EvidenceRow,
  type GapRow,
  type SealedFinding,
} from './findings';
import { STAGES } from './pipeline';
import type { Artifact, AuditDetail, ReportData, Traffic } from './types';

export interface ExtraSection {
  id: string;
  title: string;
  markdown: string;
}

export interface IncompleteReport {
  reason: string | null;
  ran: string[];
  notRun: string[];
  markdown: string | null;
}

export interface ReportModel {
  management: ReportData | null;
  /** True when the management traffic lights were derived from findings (no management report). */
  managementDerived: boolean;
  engineer: ReportData | null;
  bias: string | null;
  extra: ExtraSection[];
  gaps: GapRow[];
  evidence: EvidenceRow[];
  incomplete: IncompleteReport | null;
  /** A pipeline report artifact exists. */
  hasReport: boolean;
  pdfSha256: string | null;
}

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const str = (v: unknown) => (typeof v === 'string' && v.trim() ? v : null);
const strs = (v: unknown) =>
  Array.isArray(v) ? v.map((x) => (typeof x === 'string' ? x : JSON.stringify(x))) : [];
/** `"md"` or `{markdown}`. */
const md = (v: unknown) => str(v) ?? (isObj(v) ? str(v.markdown) : null);

const REPORT_KINDS = new Set([
  'report',
  'bias_fairness_report',
  'evidence_register',
  'gap_list',
  'incomplete_report',
  'annex_iv',
  'annex_iv_report',
]);

function live(artifacts: Artifact[]): Artifact[] {
  return artifacts.filter((a) => REPORT_KINDS.has(a.kind) && a.status !== 'superseded');
}

function gapRowsFrom(v: unknown): GapRow[] | null {
  if (!Array.isArray(v) || v.length === 0) return null;
  return v.filter(isObj).map((g, i) => ({
    gapId: str(g.gap_id) ?? str(g.id) ?? `G-${String(i + 1).padStart(2, '0')}`,
    obligationId: str(g.obligation_id) ?? '–',
    article: str(g.article),
    severity: str(g.severity),
    verdict: str(g.verdict) ?? 'gap',
    inForce: str(g.in_force_date),
    remediation: str(g.remediation) ?? str(g.remediation_proposal),
  }));
}

function evidenceRowsFrom(v: unknown): EvidenceRow[] | null {
  if (!Array.isArray(v) || v.length === 0) return null;
  return v.filter(isObj).map((e) => ({
    obligationId: str(e.obligation_id) ?? '–',
    verdict: str(e.verdict) ?? '–',
    hash: str(e.hash) ?? '',
    evidence: (Array.isArray(e.evidence_refs) ? e.evidence_refs : Array.isArray(e.evidence) ? e.evidence : [])
      .filter(isObj)
      .map((x) => ({
        path: str(x.path) ?? '–',
        sha256: str(x.sha256),
        mlflow_run_id: str(x.mlflow_run_id),
      })),
    citations: (Array.isArray(e.citations) ? e.citations : []).filter(isObj).map((c) => ({
      provision_id: str(c.provision_id) ?? '–',
      kb_version: str(c.kb_version),
    })),
  }));
}

const LIGHT: Record<string, Traffic> = {
  gap: 'red',
  indicates_gap: 'red',
  partial: 'amber',
  inconclusive: 'amber',
  pass: 'green',
  supports_compliance: 'green',
};

/** One traffic light per article (worst verdict wins) when no management report exists. */
export function derivedTraffic(findings: SealedFinding[]): ReportData['traffic'] {
  const order: Traffic[] = ['red', 'amber', 'green', 'grey'];
  const byGroup = new Map<string, { light: Traffic; notes: string[] }>();
  for (const f of findings) {
    const group = articleOf(f)?.replace(/\(.*$/, '') ?? f.obligation_id;
    const light = LIGHT[f.verdict] ?? 'grey';
    const cur = byGroup.get(group);
    const note = `${f.obligation_id}: ${f.verdict.replace(/_/g, ' ')}`;
    if (!cur) byGroup.set(group, { light, notes: [note] });
    else {
      cur.notes.push(note);
      if (order.indexOf(light) < order.indexOf(cur.light)) cur.light = light;
    }
  }
  return [...byGroup.entries()]
    .sort((a, b) => order.indexOf(a[1].light) - order.indexOf(b[1].light) || a[0].localeCompare(b[0]))
    .map(([requirement, v]) => ({ requirement, light: v.light, note: v.notes.join(' · ') }));
}

function stageLabel(id: string): string {
  return STAGES.find((s) => s.id === id)?.label ?? id;
}

export function reportModel(audit: AuditDetail, findings: SealedFinding[]): ReportModel {
  const arts = live(audit.artifacts);
  const views = reportsFromArtifacts(arts.filter((a) => !(a.kind === 'report' && a.name === 'incomplete')));
  const engineer = views.find((v) => v.report.audience === 'engineer')?.report ?? null;
  const management = views.find((v) => v.report.audience === 'management')?.report ?? null;

  let bias: string | null = null;
  let gaps: GapRow[] | null = null;
  let evidence: EvidenceRow[] | null = null;
  let incomplete: IncompleteReport | null = null;
  let pdfSha256: string | null = null;
  const extra: ExtraSection[] = [];

  for (const a of arts) {
    const d = a.data ?? {};
    if (a.kind === 'bias_fairness_report') bias = md(d) ?? bias;
    if (a.kind === 'annex_iv' || a.kind === 'annex_iv_report') {
      const m = md(d);
      if (m) extra.push({ id: 'annex-iv', title: 'Annex IV §2–3 test section (draft)', markdown: m });
    }
    if (a.kind === 'gap_list') gaps = gapRowsFrom(d.gaps ?? d.entries ?? d) ?? gaps;
    if (a.kind === 'evidence_register') evidence = evidenceRowsFrom(d.entries ?? d.register ?? d) ?? evidence;
    if (a.kind === 'incomplete_report' || (a.kind === 'report' && a.name === 'incomplete')) {
      incomplete = {
        reason: str(d.reason) ?? str(d.error),
        ran: strs(d.ran),
        notRun: strs(d.not_run ?? d.notRun),
        markdown: str(d.markdown) ?? str(d.engineer_markdown),
      };
    }
    if (a.kind === 'report') {
      bias = md(d.bias_fairness_markdown ?? d.bias_fairness) ?? bias;
      const annex = md(d.annex_iv_markdown ?? d.annex_iv);
      if (annex && !extra.some((e) => e.id === 'annex-iv'))
        extra.push({ id: 'annex-iv', title: 'Annex IV §2–3 test section (draft)', markdown: annex });
      gaps = gapRowsFrom(d.gap_list) ?? gaps;
      evidence = evidenceRowsFrom(d.evidence_register) ?? evidence;
      pdfSha256 = str(d.pdf_sha256) ?? pdfSha256;
      if (isObj(d.incomplete)) {
        const inc = d.incomplete;
        incomplete = {
          reason: str(inc.reason) ?? str(inc.error),
          ran: strs(inc.ran),
          notRun: strs(inc.not_run ?? inc.notRun),
          markdown: str(inc.markdown),
        };
      }
    }
  }

  // A failed audit with no incomplete report: say what ran and where it stopped.
  if (!incomplete && audit.status === 'failed') {
    const at = STAGES.findIndex((s) => s.id === audit.stage);
    incomplete = {
      reason: str(audit.data.error) ?? 'The pipeline stopped before the report.',
      ran: at > 0 ? STAGES.slice(0, at).map((s) => s.label) : [],
      notRun: at >= 0 ? STAGES.slice(at).map((s) => stageLabel(s.id)) : [],
      markdown: null,
    };
  }

  const traffic = derivedTraffic(findings);
  return {
    management:
      management ??
      (findings.length > 0
        ? { audience: 'management', title: undefined, markdown: '', traffic, decisions: [], nextSteps: [] }
        : null),
    managementDerived: !management && findings.length > 0,
    engineer,
    bias,
    extra,
    gaps: gaps ?? gapList(findings),
    evidence: evidence ?? evidenceRegister(findings),
    incomplete,
    hasReport: arts.some((a) => a.kind === 'report'),
    pdfSha256,
  };
}
