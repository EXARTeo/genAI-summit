// The plugin form: a flat set of text fields over plugin.yaml.
// Every field shows the default (graph + MLflow) in grey; an empty field saves the default.
import type { PluginCard } from './types';

export const FORM_FIELDS = [
  'name',
  'accessType',
  'uri',
  'url',
  'environment',
  'secretRef',
  'rps',
  'timeoutS',
  'maxRequests',
  'task',
  'outputType',
  'labelField',
  'scoreField',
  'positiveLabel',
  'must',
  'mustNot',
  'limitations',
] as const;
export type FormField = (typeof FORM_FIELDS)[number];
export type PluginFormValues = Record<FormField, string>;

const LIST_FIELDS: FormField[] = ['must', 'mustNot', 'limitations'];
const NUMBER_FIELDS: FormField[] = ['rps', 'timeoutS', 'maxRequests'];

export const ACCESS_OPTIONS = [
  { value: 'mlflow_model', label: 'MLflow model (local registry)' },
  { value: 'rest', label: 'REST endpoint (model gateway or your API)' },
] as const;

export const OUTPUT_OPTIONS = [
  { value: 'binary_classification', label: 'Yes / no + score' },
  { value: 'multiclass_classification', label: 'Class + scores' },
  { value: 'regression', label: 'Number' },
  { value: 'table', label: 'Table' },
] as const;

export function emptyForm(): PluginFormValues {
  return Object.fromEntries(FORM_FIELDS.map((f) => [f, ''])) as PluginFormValues;
}

const str = (v: unknown): string => (v == null ? '' : String(v));
const lines = (v: unknown): string => (Array.isArray(v) ? v.map(String).join('\n') : '');

/** The form's view of a card ('' where the card says nothing). */
export function formFromCard(card: PluginCard | null | undefined): PluginFormValues {
  if (!card) return emptyForm();
  const access = card.access ?? { type: '' };
  const limits = access.limits ?? {};
  const output = (card.io?.output ?? {}) as Record<string, unknown>;
  const exp = card.expected_behaviour ?? { task: '' };
  return {
    name: str(card.name),
    accessType: str(access.type),
    uri: str(access.uri),
    url: str(access.url ?? access.rest_url),
    environment: str(access.environment),
    secretRef: str(access.auth?.secret_ref),
    rps: str(limits.rps),
    timeoutS: str(limits.timeout_s),
    maxRequests: str(limits.max_requests),
    task: str(exp.task),
    outputType: str(output.type),
    labelField: str(output.label_field),
    scoreField: str(output.score_field),
    positiveLabel: str(output.positive_label),
    must: lines(exp.must),
    mustNot: lines(exp.must_not),
    limitations: lines(exp.known_limitations),
  };
}

/** The value that will be saved: what the engineer typed, else the grey default. */
export function effective(values: PluginFormValues, defaults: PluginFormValues, f: FormField): string {
  return values[f].trim() || defaults[f].trim();
}

function toNumber(v: string): number | undefined {
  if (!v) return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

function toLines(v: string): string[] {
  return v
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Problems that would stop the agent reaching the model (checked again by the backend). */
export function validateForm(
  values: PluginFormValues,
  defaults: PluginFormValues,
): Partial<Record<FormField, string>> {
  const e = (f: FormField) => effective(values, defaults, f);
  const out: Partial<Record<FormField, string>> = {};
  if (!e('name')) out.name = 'Give the plugin a name.';
  const type = e('accessType');
  if (type === 'mlflow_model' && !/^models:\/[^@/]+(@[\w-]+|\/\d+)?$/.test(e('uri')))
    out.uri = 'An MLflow model URI: models:/<name>@<alias> or models:/<name>/<version>.';
  if (type === 'rest' && !e('url'))
    out.url = 'The endpoint: a /v1/... path on the model gateway or a full URL.';
  const ref = e('secretRef');
  if (ref && !/^env:\/\/[A-Z_][A-Z0-9_]*$/.test(ref))
    out.secretRef = 'Name an environment variable: env://NAME. Never paste the secret itself.';
  for (const f of NUMBER_FIELDS) {
    const v = e(f);
    if (v && (toNumber(v) === undefined || toNumber(v)! < 0)) out[f] = 'A number, 0 or more.';
  }
  return out;
}

/**
 * The card to save. Starts from the saved card (or the defaults), so keys the form does
 * not show (scenarios, io.input_schema, placement…) are kept; each form field overrides.
 */
export function cardFromForm(
  values: PluginFormValues,
  defaultsCard: PluginCard,
  existing?: PluginCard | null,
): PluginCard {
  const defaults = formFromCard(defaultsCard);
  const e = (f: FormField) => effective(values, defaults, f);
  const base = structuredClone(existing ?? defaultsCard) as PluginCard;
  const card: PluginCard = {
    ...base,
    id: base.id ?? defaultsCard.id,
    system: base.system ?? defaultsCard.system,
    name: e('name'),
    placement: base.placement ?? defaultsCard.placement,
  };

  const type = e('accessType') || 'mlflow_model';
  const access: PluginCard['access'] = { ...(base.access ?? {}), type };
  delete access.rest_url;
  if (e('uri')) access.uri = e('uri');
  if (type === 'mlflow_model') delete access.url;
  else if (e('url')) access.url = e('url');
  if (e('environment')) access.environment = e('environment');
  const ref = e('secretRef');
  if (ref) access.auth = { ...(access.auth ?? {}), type: access.auth?.type ?? 'bearer', secret_ref: ref };
  const limits: Record<string, number> = { ...(access.limits ?? {}) };
  const setLimit = (key: string, f: FormField) => {
    const n = toNumber(e(f));
    if (n !== undefined) limits[key] = n;
  };
  setLimit('rps', 'rps');
  setLimit('timeout_s', 'timeoutS');
  setLimit('max_requests', 'maxRequests');
  if (Object.keys(limits).length) access.limits = limits;
  card.access = access;

  const output: Record<string, unknown> = { ...((base.io?.output as Record<string, unknown>) ?? {}) };
  const outType = e('outputType');
  if (outType) output.type = outType;
  if (outType === 'binary_classification' || outType === 'multiclass_classification') {
    if (e('labelField')) output.label_field = e('labelField');
    if (e('scoreField')) output.score_field = e('scoreField');
    const pos = e('positiveLabel');
    if (pos) output.positive_label = toNumber(pos) ?? pos;
  }
  card.io = { ...(base.io ?? {}), output };

  card.expected_behaviour = {
    ...(base.expected_behaviour ?? { task: '' }),
    task: e('task'),
    must: toLines(e('must')),
    must_not: toLines(e('mustNot')),
    known_limitations: toLines(e('limitations')),
  };
  return card;
}

/** Fields the engineer changed from the default (for the "N overrides" hint). */
export function overrides(values: PluginFormValues, defaults: PluginFormValues): FormField[] {
  return FORM_FIELDS.filter((f) => values[f].trim() && values[f].trim() !== defaults[f].trim());
}

export { LIST_FIELDS };
