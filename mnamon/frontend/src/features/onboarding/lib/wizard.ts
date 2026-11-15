// The "Register a system" wizard (plan 02 §5): form state, per-step validation, the example,
// and the system card it writes. Pure: no React, no API.
import { stringify } from 'yaml';

/** Mirrors the backend's SYSTEM_ID_PATTERN (schema/systems.py). */
export const SYSTEM_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

export const STEPS = [
  { id: 'identity', title: 'Identity' },
  { id: 'purpose', title: 'Purpose' },
  { id: 'deployment', title: 'Deployment' },
  { id: 'documents', title: 'Documents' },
  { id: 'review', title: 'Review' },
] as const;
export type StepId = (typeof STEPS)[number]['id'];

/** How the organisation got the system (feeds the Art. 25 role pre-check). */
export type Acquisition = 'in_house' | 'as_is' | 'modified';
export type YesNoUnsure = 'yes' | 'no' | 'unknown';
export type DeploymentStatus = 'planned' | 'pilot' | 'production';

export const FEATURES = [
  {
    id: 'interacts_with_persons',
    label: 'Interacts directly with people',
    hint: 'A chatbot, voice agent or any interface where people talk to the system.',
  },
  {
    id: 'generates_synthetic_content',
    label: 'Generates text, images, audio or video',
    hint: 'Synthetic content people may take for real (Art. 50(2)).',
  },
  {
    id: 'emotion_recognition',
    label: 'Recognises emotions',
    hint: 'Infers emotions or intentions from faces, voice or text.',
  },
  {
    id: 'biometric',
    label: 'Uses biometric data',
    hint: 'Faces, fingerprints, voice prints or other data that identify a person.',
  },
] as const;
export type Feature = (typeof FEATURES)[number]['id'];

export interface WizardForm {
  id: string;
  name: string;
  organisation: string;
  acquisition: Acquisition | '';
  description: string;
  intended_purpose: string;
  decision_informed: string;
  human_oversight: string;
  profiling: YesNoUnsure | '';
  countries: string;
  users: string;
  deployment_status: DeploymentStatus;
  affected_persons: string;
  vulnerable_groups: string;
  features: Feature[];
  safety_component: boolean;
  annex_i_product: string;
}

export const EMPTY_FORM: WizardForm = {
  id: '',
  name: '',
  organisation: '',
  acquisition: '',
  description: '',
  intended_purpose: '',
  decision_informed: '',
  human_oversight: '',
  profiling: '',
  countries: '',
  users: '',
  deployment_status: 'planned',
  affected_persons: '',
  vulnerable_groups: '',
  features: [],
  safety_component: false,
  annex_i_product: '',
};

/** The demo's "Fill example" (plan 02 §11): a CV parser that only structures CVs. */
export function exampleForm(id: string): WizardForm {
  return {
    ...EMPTY_FORM,
    id,
    name: 'CV Parser',
    organisation: 'Acme Talent Services',
    acquisition: 'in_house',
    description:
      'Extracts structured fields (contact details, work history, education, skills, languages) from CVs uploaded as PDF or Word files, so recruiters do not retype them into the applicant tracking system.',
    intended_purpose:
      'Turn incoming CVs into structured candidate records for recruiters. It does not score, rank, filter or reject candidates.',
    decision_informed:
      'None directly: recruiters read the structured record and decide whom to shortlist themselves.',
    human_oversight:
      'Recruiters see the original CV next to the extracted fields and correct any field before saving.',
    profiling: 'no',
    countries: 'GR, CY',
    users: 'In-house recruiters (about 40)',
    deployment_status: 'pilot',
    affected_persons: 'Job applicants whose CVs are processed',
    vulnerable_groups: '',
    features: [],
    safety_component: false,
    annex_i_product: '',
  };
}

/** `SYS-001..SYS-003` taken → `SYS-004`. */
export function nextSystemId(taken: string[]): string {
  const nums = taken
    .map((t) => /^SYS-(\d+)$/i.exec(t)?.[1])
    .filter(Boolean)
    .map(Number);
  const next = (nums.length ? Math.max(...nums) : 0) + 1;
  return `SYS-${String(next).padStart(3, '0')}`;
}

export type Errors = Partial<Record<keyof WizardForm, string>>;

/** Validation of one step; `taken` = ids already in use. */
export function stepErrors(step: StepId, f: WizardForm, taken: string[] = []): Errors {
  const e: Errors = {};
  if (step === 'identity') {
    const id = f.id.trim();
    if (!id) e.id = 'Give the system an id.';
    else if (!SYSTEM_ID_PATTERN.test(id))
      e.id = 'Letters, digits, ".", "_" or "-", starting with a letter or digit (max 64).';
    else if (taken.some((t) => t.toLowerCase() === id.toLowerCase())) e.id = `${id} is already registered.`;
    if (!f.name.trim()) e.name = 'Give the system a name.';
    if (!f.acquisition) e.acquisition = 'Pick how you got the system: it decides provider or deployer.';
  }
  if (step === 'purpose') {
    if (f.description.trim().length < 20)
      e.description = 'Describe what the system does (at least a sentence).';
    if (f.intended_purpose.trim().length < 10) e.intended_purpose = 'The intended purpose is required.';
    if (!f.profiling) e.profiling = 'Answer yes, no or not sure.';
  }
  if (step === 'deployment') {
    if (!f.affected_persons.trim()) e.affected_persons = 'Who is affected by its output?';
    if (f.safety_component && !f.annex_i_product.trim())
      e.annex_i_product = 'Name the product law (e.g. machinery, medical devices).';
  }
  return e;
}

/** The first step (index) with errors, or -1. */
export function firstInvalidStep(f: WizardForm, taken: string[] = []): number {
  return STEPS.findIndex((s) => Object.keys(stepErrors(s.id, f, taken)).length > 0);
}

const list = (s: string) =>
  s
    .split(/[,;\n]/)
    .map((x) => x.trim())
    .filter(Boolean);

/** The system card the PM declares (`risk_class: unclassified` until a classification is approved). */
export function buildCard(f: WizardForm): Record<string, unknown> {
  const opt = (s: string) => s.trim() || null;
  return {
    id: f.id.trim(),
    name: f.name.trim(),
    organisation: opt(f.organisation),
    card_version: 1,
    risk_class: 'unclassified',
    annex_basis: null,
    role: null,
    acquisition: f.acquisition || null,
    description: f.description.trim(),
    intended_purpose: f.intended_purpose.trim(),
    decision_informed: opt(f.decision_informed),
    human_oversight: opt(f.human_oversight),
    profiling: f.profiling || 'unknown',
    deployment: {
      status: f.deployment_status,
      countries: list(f.countries),
      users: opt(f.users),
    },
    affected_persons: f.affected_persons.trim(),
    vulnerable_groups: opt(f.vulnerable_groups),
    features: [...f.features],
    annex_i_product: f.safety_component ? opt(f.annex_i_product) : null,
    provenance: 'declared_by_pm',
  };
}

export function cardYaml(card: Record<string, unknown>): string {
  return (
    '# System card declared by the PM in the Register a system wizard.\n' +
    '# risk_class stays "unclassified" until a classification is approved.\n' +
    stringify(card)
  );
}

/** Documents the classifier reads (plan 02 §3); other files are stored and listed as "not read". */
export const READABLE = /\.(md|markdown|txt|ya?ml|json)$/i;
export const isReadable = (name: string) => READABLE.test(name);

/** Where an uploaded document lands in the system folder. */
export function docPath(name: string): string {
  const clean = name
    .replace(/[\\/]+/g, '-')
    .replace(/\s+/g, '-')
    .replace(/^[.-]+/, '');
  return `docs/${clean || 'document'}`;
}

/** Drop duplicates by name (a later pick replaces the earlier file). */
export function mergeFiles(current: File[], added: File[]): File[] {
  const byName = new Map(current.map((f) => [f.name, f]));
  for (const f of added) byName.set(f.name, f);
  return [...byName.values()];
}

export const ACQUISITION_OPTIONS: { value: Acquisition; label: string; hint: string }[] = [
  { value: 'in_house', label: 'Built in-house', hint: 'We developed it: usually the provider.' },
  { value: 'as_is', label: 'Bought or licensed, used as is', hint: 'Usually a deployer.' },
  {
    value: 'modified',
    label: 'Bought, then changed or rebranded',
    hint: 'A substantial change or our name on it makes us the provider (Art. 25).',
  },
];

export const PROFILING_OPTIONS: { value: YesNoUnsure; label: string }[] = [
  { value: 'yes', label: 'Yes' },
  { value: 'no', label: 'No' },
  { value: 'unknown', label: 'Not sure' },
];

export const DEPLOYMENT_OPTIONS: { value: DeploymentStatus; label: string }[] = [
  { value: 'planned', label: 'Planned' },
  { value: 'pilot', label: 'Pilot' },
  { value: 'production', label: 'In production' },
];
