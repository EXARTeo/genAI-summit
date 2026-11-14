// Pure presentation mappings: verdicts, gates, traffic lights, provenance.
// Colours are Tailwind semantic utility names so they follow the brand tokens (no hex here).
import type { GateName, GateResult, GateStatus, Provenance, Traffic, Verdict } from './types';

export type Tone = 'success' | 'danger' | 'warning' | 'neutral' | 'info';

export interface VerdictStyle {
  label: string;
  tone: Tone;
  short: string;
  description: string;
}

export const VERDICTS: Record<Verdict, VerdictStyle> = {
  supports_compliance: {
    label: 'Supports compliance',
    short: 'Supports',
    tone: 'success',
    description: 'The evidence supports the requirement within the stated limits.',
  },
  indicates_gap: {
    label: 'Indicates a gap',
    short: 'Gap',
    tone: 'danger',
    description: 'The evidence points to a gap that needs action.',
  },
  inconclusive: {
    label: 'Inconclusive',
    short: 'Inconclusive',
    tone: 'warning',
    description: 'The evidence does not settle the question; see "would change if".',
  },
  not_assessable_by_testing: {
    label: 'Not assessable by testing',
    short: 'Not testable',
    tone: 'neutral',
    description: 'Needs documentation or process review, not a test.',
  },
};

export function verdictStyle(v: string): VerdictStyle {
  return VERDICTS[v as Verdict] ?? { label: v, short: v, tone: 'neutral', description: '' };
}

/** Tailwind classes per tone (semantic tokens from brand.json via CSS vars). */
export const TONE_CLASSES: Record<
  Tone,
  { pill: string; dot: string; text: string; ring: string; bg: string }
> = {
  success: {
    pill: 'bg-success/10 text-success border-success/20',
    dot: 'bg-success',
    text: 'text-success',
    ring: 'ring-success/40',
    bg: 'bg-success',
  },
  danger: {
    pill: 'bg-danger/10 text-danger border-danger/20',
    dot: 'bg-danger',
    text: 'text-danger',
    ring: 'ring-danger/40',
    bg: 'bg-danger',
  },
  warning: {
    pill: 'bg-warning/10 text-warning border-warning/20',
    dot: 'bg-warning',
    text: 'text-warning',
    ring: 'ring-warning/40',
    bg: 'bg-warning',
  },
  info: {
    pill: 'bg-info/10 text-info border-info/20',
    dot: 'bg-info',
    text: 'text-info',
    ring: 'ring-info/40',
    bg: 'bg-info',
  },
  neutral: {
    pill: 'bg-surface-muted text-muted border-border',
    dot: 'bg-muted',
    text: 'text-muted',
    ring: 'ring-border',
    bg: 'bg-muted',
  },
};

export const GATE_ORDER: GateName[] = ['schema', 'business_rules', 'realism', 'coverage', 'privacy'];

export const GATE_LABELS: Record<GateName, { label: string; checks: string; failAction: string }> = {
  schema: { label: 'Schema', checks: 'Types, enums, ranges, model input signature', failAction: 'Block' },
  business_rules: {
    label: 'Business rules',
    checks: 'Hard rules = 0 violations; soft rules within tolerance',
    failAction: 'Block (hard) / warn (soft)',
  },
  realism: {
    label: 'Realism',
    checks: 'Marginals and correlations vs training-data.md',
    failAction: 'Warn + show at review',
  },
  coverage: {
    label: 'Coverage',
    checks: 'Every protected group × stratum ≥ min_per_cell',
    failAction: 'Top-up, else block',
  },
  privacy: {
    label: 'Privacy',
    checks: 'No real PII; Presidio scan; DCR when a reference exists',
    failAction: 'Block',
  },
};

export function gateTone(s: GateStatus | string): Tone {
  return s === 'pass' ? 'success' : s === 'warn' ? 'warning' : s === 'fail' ? 'danger' : 'neutral';
}

/** Overall gate status: any fail → fail, any warn → warn, else pass. Missing gates count as fail. */
export function overallGateStatus(gates: Partial<Record<GateName, GateResult>>): GateStatus {
  const statuses = GATE_ORDER.map((g) => gates[g]?.status ?? 'fail');
  if (statuses.includes('fail')) return 'fail';
  if (statuses.includes('warn')) return 'warn';
  return 'pass';
}

export function gateCounts(gates: Partial<Record<GateName, GateResult>>): Record<GateStatus, number> {
  const out: Record<GateStatus, number> = { pass: 0, warn: 0, fail: 0 };
  for (const g of GATE_ORDER) out[gates[g]?.status ?? 'fail'] += 1;
  return out;
}

/** Datasets can be approved only when no gate blocks (fail). Warnings need a human look. */
export function canApproveDataset(gates: Partial<Record<GateName, GateResult>>): boolean {
  return overallGateStatus(gates) !== 'fail';
}

export function trafficTone(t: Traffic | string): Tone {
  return t === 'green' ? 'success' : t === 'amber' ? 'warning' : t === 'red' ? 'danger' : 'neutral';
}

/** Management traffic light from a verdict (critic-adjusted verdicts are already final). */
export function verdictToTraffic(v: Verdict | string): Traffic {
  switch (v) {
    case 'supports_compliance':
      return 'green';
    case 'indicates_gap':
      return 'red';
    case 'inconclusive':
      return 'amber';
    default:
      return 'grey';
  }
}

export const PROVENANCE: Record<Provenance, { label: string; tone: Tone }> = {
  dictionary: { label: 'dictionary', tone: 'success' },
  training_doc: { label: 'training doc', tone: 'info' },
  business_rule: { label: 'business rule', tone: 'info' },
  llm_assumption: { label: 'LLM assumption', tone: 'warning' },
};

/** Split a YAML line into the part before a `provenance:` tag and the tag value (if any). */
export function provenanceOfLine(line: string): Provenance | null {
  const m = line.match(/provenance:\s*([a-z_]+)/);
  if (!m) return null;
  return (m[1] in PROVENANCE ? m[1] : null) as Provenance | null;
}

export function confidenceLabel(c: number): string {
  if (c >= 0.8) return 'high';
  if (c >= 0.55) return 'medium';
  return 'low';
}

export function formatCI(ci?: [number, number], digits = 2): string {
  if (!ci) return '';
  return `95% CI [${ci[0].toFixed(digits)}, ${ci[1].toFixed(digits)}]`;
}

/** Does the CI cross the threshold? Used to explain inconclusive verdicts. */
export function ciCrosses(ci: [number, number], threshold: number): boolean {
  return ci[0] < threshold && ci[1] > threshold;
}
