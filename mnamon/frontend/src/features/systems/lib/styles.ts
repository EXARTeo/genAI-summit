import type { BadgeTone } from '@/shared/ui';

export const RISK_META: Record<string, { label: string; tone: BadgeTone; short: string }> = {
  prohibited: { label: 'Prohibited', tone: 'danger', short: 'Art. 5' },
  high_risk: { label: 'High risk', tone: 'danger', short: 'Annex III' },
  limited_risk: { label: 'Limited risk', tone: 'warning', short: 'Art. 50' },
  minimal_risk: { label: 'Minimal risk', tone: 'success', short: 'Minimal' },
};

export function riskMeta(risk?: string) {
  // A registered system's card says `unclassified` until a classification is approved (plan 02).
  const known = risk && risk !== 'unclassified' ? risk : '';
  return (
    RISK_META[known] ?? {
      label: known ? known.replace(/_/g, ' ') : 'Unclassified',
      tone: 'neutral' as BadgeTone,
      short: '',
    }
  );
}

export const ACCESS_LABEL: Record<string, string> = {
  mlflow_model: 'MLflow model',
  rest: 'REST endpoint',
  llm_chat: 'LLM chat',
  batch_file: 'Batch file',
  dataset_only: 'Dataset only',
};

/** Language for CodeBlock from a file name. */
export function languageFor(path: string): 'yaml' | 'json' | 'csv' | 'markdown' | 'text' {
  if (/\.ya?ml$/i.test(path)) return 'yaml';
  if (/\.json$/i.test(path)) return 'json';
  if (/\.csv$/i.test(path)) return 'csv';
  if (/\.md$/i.test(path)) return 'markdown';
  return 'text';
}
