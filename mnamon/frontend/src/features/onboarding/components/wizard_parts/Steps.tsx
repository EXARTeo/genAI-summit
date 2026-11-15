import { FileText, Pencil, Trash2 } from 'lucide-react';
import type { ReactNode } from 'react';
import { formatBytes } from '@/shared/lib/format';
import {
  Badge,
  Button,
  Field,
  FileDropzone,
  IconButton,
  Input,
  KeyValue,
  Switch,
  Textarea,
} from '@/shared/ui';
import {
  ACQUISITION_OPTIONS,
  DEPLOYMENT_OPTIONS,
  FEATURES,
  PROFILING_OPTIONS,
  docPath,
  isReadable,
  type Errors,
  type StepId,
  type WizardForm,
} from '../../lib/wizard';
import { ChoiceCards } from './ChoiceCards';

export interface StepProps {
  form: WizardForm;
  set: <K extends keyof WizardForm>(key: K, value: WizardForm[K]) => void;
  errors: Errors;
}

export function IdentityStep({ form, set, errors }: StepProps) {
  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-[12rem_1fr]">
        <Field
          label="System id"
          htmlFor="reg-id"
          error={errors.id}
          hint="Used in audit ids and the folder path."
        >
          <Input
            id="reg-id"
            value={form.id}
            onChange={(e) => set('id', e.target.value)}
            invalid={!!errors.id}
            className="font-mono"
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        <Field label="Name" htmlFor="reg-name" error={errors.name}>
          <Input
            id="reg-name"
            value={form.name}
            onChange={(e) => set('name', e.target.value)}
            invalid={!!errors.name}
            placeholder="e.g. CV Parser"
            maxLength={200}
          />
        </Field>
      </div>
      <Field label="Organisation" htmlFor="reg-org" hint="Optional: the legal entity that runs it.">
        <Input
          id="reg-org"
          value={form.organisation}
          onChange={(e) => set('organisation', e.target.value)}
          placeholder="e.g. Acme Talent Services"
        />
      </Field>
      <ChoiceCards
        name="acquisition"
        label="How did you get this system?"
        value={form.acquisition}
        onChange={(v) => set('acquisition', v)}
        options={ACQUISITION_OPTIONS}
        error={errors.acquisition}
      />
    </div>
  );
}

export function PurposeStep({ form, set, errors }: StepProps) {
  return (
    <div className="space-y-5">
      <Field
        label="What does it do?"
        htmlFor="reg-desc"
        error={errors.description}
        hint="Plain words: inputs, outputs, who uses it."
      >
        <Textarea
          id="reg-desc"
          value={form.description}
          onChange={(e) => set('description', e.target.value)}
          invalid={!!errors.description}
          rows={3}
        />
      </Field>
      <Field
        label="Intended purpose"
        htmlFor="reg-purpose"
        error={errors.intended_purpose}
        hint="What it is for, as you would state it in the instructions for use. Say what it does not do, too."
      >
        <Textarea
          id="reg-purpose"
          value={form.intended_purpose}
          onChange={(e) => set('intended_purpose', e.target.value)}
          invalid={!!errors.intended_purpose}
          rows={2}
        />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Decision it informs"
          htmlFor="reg-decision"
          hint="Optional: which human or automated decision uses the output."
        >
          <Textarea
            id="reg-decision"
            value={form.decision_informed}
            onChange={(e) => set('decision_informed', e.target.value)}
            rows={2}
          />
        </Field>
        <Field
          label="Human oversight"
          htmlFor="reg-oversight"
          hint="Optional: who checks the output, and how."
        >
          <Textarea
            id="reg-oversight"
            value={form.human_oversight}
            onChange={(e) => set('human_oversight', e.target.value)}
            rows={2}
          />
        </Field>
      </div>
      <ChoiceCards
        name="profiling"
        label="Does it evaluate or predict personal aspects of people?"
        hint="Performance at work, reliability, behaviour, location, health, preferences. If yes, the Art. 6(3) derogation never applies."
        value={form.profiling}
        onChange={(v) => set('profiling', v)}
        options={PROFILING_OPTIONS}
        error={errors.profiling}
      />
    </div>
  );
}

function SwitchRow({
  id,
  label,
  hint,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  hint: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-3 first:pt-0 last:pb-0">
      <div className="min-w-0">
        <label htmlFor={id} className="cursor-pointer text-sm font-medium">
          {label}
        </label>
        <p id={`${id}-hint`} className="text-xs text-muted">
          {hint}
        </p>
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onChange} aria-describedby={`${id}-hint`} />
    </div>
  );
}

export function DeploymentStep({ form, set, errors }: StepProps) {
  const toggle = (f: WizardForm['features'][number], on: boolean) =>
    set('features', on ? [...new Set([...form.features, f])] : form.features.filter((x) => x !== f));
  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Countries" htmlFor="reg-countries" hint="Where it is or will be used, comma-separated.">
          <Input
            id="reg-countries"
            value={form.countries}
            onChange={(e) => set('countries', e.target.value)}
            placeholder="e.g. GR, CY"
          />
        </Field>
        <Field label="Users" htmlFor="reg-users" hint="Who operates it.">
          <Input
            id="reg-users"
            value={form.users}
            onChange={(e) => set('users', e.target.value)}
            placeholder="e.g. In-house recruiters"
          />
        </Field>
      </div>
      <ChoiceCards
        name="deployment_status"
        label="Status"
        value={form.deployment_status}
        onChange={(v) => set('deployment_status', v)}
        options={DEPLOYMENT_OPTIONS}
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Affected persons" htmlFor="reg-affected" error={errors.affected_persons}>
          <Input
            id="reg-affected"
            value={form.affected_persons}
            onChange={(e) => set('affected_persons', e.target.value)}
            invalid={!!errors.affected_persons}
            placeholder="e.g. Job applicants"
          />
        </Field>
        <Field
          label="Vulnerable groups"
          htmlFor="reg-vulnerable"
          hint="Optional: children, people with disabilities, ..."
        >
          <Input
            id="reg-vulnerable"
            value={form.vulnerable_groups}
            onChange={(e) => set('vulnerable_groups', e.target.value)}
          />
        </Field>
      </div>

      <fieldset>
        <legend className="mb-2 text-sm font-medium">What else does it do?</legend>
        <div className="divide-y divide-border rounded-lg border border-border px-4 py-3">
          {FEATURES.map((f) => (
            <SwitchRow
              key={f.id}
              id={`reg-f-${f.id}`}
              label={f.label}
              hint={f.hint}
              checked={form.features.includes(f.id)}
              onChange={(on) => toggle(f.id, on)}
            />
          ))}
          <SwitchRow
            id="reg-safety"
            label="Safety component of a regulated product"
            hint="Or itself a product under EU product law (Annex I): machinery, toys, medical devices, ..."
            checked={form.safety_component}
            onChange={(on) => set('safety_component', on)}
          />
        </div>
      </fieldset>
      {form.safety_component && (
        <Field label="Which product law?" htmlFor="reg-annex-i" error={errors.annex_i_product}>
          <Input
            id="reg-annex-i"
            value={form.annex_i_product}
            onChange={(e) => set('annex_i_product', e.target.value)}
            invalid={!!errors.annex_i_product}
            placeholder="e.g. Machinery Regulation (EU) 2023/1230"
          />
        </Field>
      )}
    </div>
  );
}

export function DocumentsStep({
  files,
  onAdd,
  onRemove,
}: {
  files: File[];
  onAdd: (files: File[]) => void;
  onRemove: (name: string) => void;
}) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">
        Specifications, model descriptions, DPIAs: whatever describes the system. They land in the system
        folder under <code className="font-mono text-xs">docs/</code>. The classifier reads Markdown, text,
        YAML and JSON; other files are stored and listed as not read.
      </p>
      <FileDropzone
        onFiles={onAdd}
        title="Drop documents here or click to browse"
        hint=".md, .txt, .yaml, .json are read · PDF and others are stored"
        className="py-6"
      />
      {files.length > 0 ? (
        <ul
          className="divide-y divide-border rounded-lg border border-border"
          aria-label="Documents to upload"
        >
          {files.map((f) => (
            <li key={f.name} className="flex items-center gap-3 px-3 py-2">
              <FileText className="size-4 shrink-0 text-muted" aria-hidden />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm">{f.name}</div>
                <div className="truncate font-mono text-2xs text-muted">
                  {docPath(f.name)} · {formatBytes(f.size)}
                </div>
              </div>
              {isReadable(f.name) ? <Badge tone="success">Read</Badge> : <Badge>Stored, not read</Badge>}
              <IconButton
                label={`Remove ${f.name}`}
                icon={<Trash2 />}
                size="icon-sm"
                onClick={() => onRemove(f.name)}
              />
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted">
          Optional, but a specification makes the classification much sharper.
        </p>
      )}
    </div>
  );
}

function ReviewSection({
  title,
  onEdit,
  children,
}: {
  title: string;
  onEdit: () => void;
  children: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-border p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        <Button variant="ghost" size="sm" leftIcon={<Pencil />} onClick={onEdit} aria-label={`Edit ${title}`}>
          Edit
        </Button>
      </div>
      {children}
    </section>
  );
}

const labelOf = <T extends string>(opts: { value: T; label: string }[], v: string) =>
  opts.find((o) => o.value === v)?.label ?? (v || '—');

export function ReviewStep({
  form,
  files,
  goTo,
}: {
  form: WizardForm;
  files: File[];
  goTo: (step: StepId) => void;
}) {
  const features = FEATURES.filter((f) => form.features.includes(f.id)).map((f) => f.label);
  return (
    <div className="space-y-3">
      <ReviewSection title="Identity" onEdit={() => goTo('identity')}>
        <KeyValue
          items={[
            { label: 'Id', value: form.id, mono: true },
            { label: 'Name', value: form.name },
            { label: 'Organisation', value: form.organisation || null },
            { label: 'How you got it', value: labelOf(ACQUISITION_OPTIONS, form.acquisition) },
          ]}
        />
      </ReviewSection>
      <ReviewSection title="Purpose" onEdit={() => goTo('purpose')}>
        <KeyValue
          columns={1}
          items={[
            { label: 'What it does', value: form.description },
            { label: 'Intended purpose', value: form.intended_purpose },
            { label: 'Decision it informs', value: form.decision_informed || null },
            { label: 'Human oversight', value: form.human_oversight || null },
            { label: 'Profiles people', value: labelOf(PROFILING_OPTIONS, form.profiling) },
          ]}
        />
      </ReviewSection>
      <ReviewSection title="Deployment and people" onEdit={() => goTo('deployment')}>
        <KeyValue
          items={[
            { label: 'Countries', value: form.countries || null },
            { label: 'Users', value: form.users || null },
            { label: 'Status', value: labelOf(DEPLOYMENT_OPTIONS, form.deployment_status) },
            { label: 'Affected persons', value: form.affected_persons },
            { label: 'Vulnerable groups', value: form.vulnerable_groups || null },
            {
              label: 'Also',
              value: features.length ? (
                <span className="flex flex-wrap gap-1">
                  {features.map((f) => (
                    <Badge key={f} tone="primary">
                      {f}
                    </Badge>
                  ))}
                </span>
              ) : (
                'None of the listed features'
              ),
            },
            ...(form.safety_component ? [{ label: 'Annex I product law', value: form.annex_i_product }] : []),
          ]}
        />
      </ReviewSection>
      <ReviewSection title={`Documents (${files.length})`} onEdit={() => goTo('documents')}>
        {files.length ? (
          <ul className="space-y-1 text-sm">
            {files.map((f) => (
              <li key={f.name} className="flex items-center justify-between gap-2">
                <span className="truncate font-mono text-xs">{docPath(f.name)}</span>
                {isReadable(f.name) ? <Badge tone="success">Read</Badge> : <Badge>Not read</Badge>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">No documents.</p>
        )}
      </ReviewSection>
      <p className="px-1 text-xs text-muted">
        Creates <span className="font-mono">{form.id}</span> as a <span className="font-medium">draft</span>{' '}
        with <span className="font-mono">system-card.yaml</span> (risk class unclassified) and its documents.
        No models or pipeline: the AI engineer adds those later in the Plugins tab.
      </p>
    </div>
  );
}
