import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  CheckCircle2,
  FileText,
  RotateCcw,
  Trash2,
  Upload,
  Wand2,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { formatBytes } from '@/shared/lib/format';
import { cn } from '@/shared/lib/utils';
import { Badge, Button, Field, Input, Select, Sheet, Skeleton, Textarea, toast } from '@/shared/ui';
import { usePluginDefaults, useRemoveComponent, useSavePlugin } from '../../hooks/usePlugins';
import { useSystemFiles, useUploadFiles } from '../../hooks/useSystems';
import {
  ACCESS_OPTIONS,
  OUTPUT_OPTIONS,
  cardFromForm,
  effective,
  emptyForm,
  formFromCard,
  overrides,
  validateForm,
  type FormField,
  type PluginFormValues,
} from '../../lib/pluginForm';
import type { GraphComponent, MlflowModelInfo, PluginGraph } from '../../lib/types';
import { ConnectionFields, connection, nextExampleModel } from './GraphStepDialog';

const SLUG = /^[a-z0-9][a-z0-9-]{0,62}$/;

function Block({ title, hint, children }: { title: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-4">
      <div>
        <h3 className="font-heading text-lg leading-tight">{title}</h3>
        {hint && <p className="mt-0.5 text-xs text-muted">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

function MlflowBanner({ info, uri }: { info: MlflowModelInfo; uri: string }) {
  if (info.status === 'ok') {
    return (
      <div className="flex items-start gap-3 rounded-xl border border-success/30 bg-success/5 px-3.5 py-3 text-sm">
        <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
        <div className="min-w-0">
          <div className="font-medium">
            Found in MLflow: <span className="font-mono text-xs">{info.name}</span>
            {info.version && <span className="text-muted"> · version {info.version}</span>}
            {info.alias && <span className="text-muted"> · @{info.alias}</span>}
          </div>
          <p className="mt-0.5 text-xs text-muted">
            The grey values below come from the registry and the system graph. Leave a field empty to keep its
            default.
          </p>
        </div>
      </div>
    );
  }
  const msg =
    info.status === 'not_mlflow'
      ? 'Not an MLflow model: defaults come from the system graph only.'
      : info.status === 'not_found'
        ? `MLflow has no model at ${uri || 'this URI'}. Check the name and alias.`
        : 'MLflow is not reachable right now: defaults come from the system graph only.';
  return (
    <div className="flex items-start gap-3 rounded-xl border border-warning/30 bg-warning/5 px-3.5 py-3 text-sm">
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
      <p className="min-w-0 break-words">{msg}</p>
    </div>
  );
}

/** Files under plugins/<name>/: docs and data the agent reads, with uploads. */
function PluginFiles({ systemId, folder }: { systemId: string; folder: string }) {
  const files = useSystemFiles(systemId);
  const upload = useUploadFiles(systemId);
  const picker = useRef<HTMLInputElement>(null);
  const target = useRef('docs');
  const prefix = `plugins/${folder}/`;
  const list = (files.data ?? []).filter((f) => f.path.startsWith(prefix) && !/plugin\.ya?ml$/.test(f.path));
  const hasDictionary = list.some((f) => f.path === `${prefix}data/data-dictionary.yaml`);

  const pick = (sub: string) => {
    target.current = sub;
    picker.current?.click();
  };

  return (
    <Block
      title="Docs and data"
      hint="What the agent reads about this model: model card, API notes, training data."
    >
      {!hasDictionary && (
        <div className="flex items-start gap-3 rounded-xl border border-warning/30 bg-warning/5 px-3.5 py-3 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <p>
            Audits need <code className="font-mono text-xs">data/data-dictionary.yaml</code>: the input fields
            the agent generates synthetic test data for.
          </p>
        </div>
      )}
      {list.length > 0 ? (
        <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border">
          {list.map((f) => (
            <li key={f.path} className="flex items-center gap-3 px-3 py-2 text-sm">
              <FileText className="size-4 shrink-0 text-muted" aria-hidden />
              <span className="min-w-0 flex-1 truncate font-mono text-xs">{f.path.slice(prefix.length)}</span>
              <span className="shrink-0 text-2xs tabular-nums text-muted">
                v{f.version} · {formatBytes(f.size)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">No files yet.</p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" size="sm" loading={upload.isPending} onClick={() => pick('docs')}>
          <Upload /> Add docs
        </Button>
        <Button variant="secondary" size="sm" loading={upload.isPending} onClick={() => pick('data')}>
          <Upload /> Add data files
        </Button>
      </div>
      <input
        ref={picker}
        type="file"
        multiple
        accept=".md,.yaml,.yml,.json,.csv,.txt,.pdf"
        className="hidden"
        onChange={(e) => {
          const chosen = Array.from(e.target.files ?? []);
          e.target.value = '';
          if (!chosen.length) return;
          const where = `${prefix}${target.current}`;
          toast.promise(upload.mutateAsync({ files: chosen, folder: where }), {
            loading: `Uploading to ${target.current}/…`,
            success: `Saved in ${target.current}/`,
            error: (err) => `Upload failed: ${err instanceof Error ? err.message : String(err)}`,
          });
        }}
      />
    </Block>
  );
}

export interface PluginEditorTarget {
  /** A graph component (a model box), or null for a standalone plugin. */
  component: GraphComponent | null;
}

/**
 * Configure the plugin of one model: every field shows its default (graph + MLflow) in grey;
 * an empty field saves the default. Saves plugins/<name>/plugin.yaml (a new version).
 */
export function PluginEditorSheet({
  systemId,
  graph,
  target,
  onOpenChange,
}: {
  systemId: string;
  graph: PluginGraph;
  target: PluginEditorTarget | null;
  onOpenChange: (open: boolean) => void;
}) {
  const component = target?.component ?? null;
  const standalone = !!target && !component;
  // Standalone: the engineer names the model first, then the defaults load.
  const [modelUri, setModelUri] = useState('');
  const [folder, setFolder] = useState('');
  const [lookup, setLookup] = useState<{ model?: string; name?: string } | null>(null);
  const [upstream, setUpstream] = useState('');
  const [downstream, setDownstream] = useState('');
  const remove = useRemoveComponent(systemId);

  const query = component ? { component: component.id } : lookup;
  const defaultsQ = usePluginDefaults(systemId, target ? query : null);
  const save = useSavePlugin(systemId);
  const data = defaultsQ.data;

  const defaults = useMemo(() => formFromCard(data?.defaults), [data]);
  const [values, setValues] = useState<PluginFormValues>(emptyForm());
  const [touched, setTouched] = useState(false);
  const [autoFilled, setAutoFilled] = useState(false);

  // Saved values that equal the default show as empty (grey), so overrides stand out.
  useEffect(() => {
    if (!data) return;
    const saved = formFromCard(data.existing);
    const next = emptyForm();
    for (const f of Object.keys(next) as FormField[]) {
      next[f] = saved[f] && saved[f].trim() !== defaults[f].trim() ? saved[f] : '';
    }
    setValues(next);
    setTouched(false);
    setAutoFilled(false);
  }, [data, defaults]);

  /** Auto fill: the seed case's hand-written plugin for this model (behaviour, limits, output). */
  const autoFill = () => {
    if (!data?.example) return;
    const ex = formFromCard(data.example);
    const next = emptyForm();
    for (const f of Object.keys(next) as FormField[]) {
      next[f] = ex[f] && ex[f].trim() !== defaults[f].trim() ? ex[f] : '';
    }
    setValues(next);
    setAutoFilled(true);
  };

  useEffect(() => {
    if (!target) {
      setModelUri('');
      setFolder('');
      setLookup(null);
      setUpstream('');
      setDownstream('');
    }
  }, [target]);

  const errors = touched ? validateForm(values, defaults) : {};
  const changed = overrides(values, defaults);
  const set = (f: FormField) => (v: string) => setValues((s) => ({ ...s, [f]: v }));
  const input = (f: FormField, extra?: { mono?: boolean; type?: string }) => (
    <Input
      id={`plugin-${f}`}
      value={values[f]}
      placeholder={defaults[f] || undefined}
      onChange={(e) => set(f)(e.target.value)}
      invalid={!!errors[f]}
      type={extra?.type}
      className={cn(extra?.mono && 'font-mono text-xs')}
    />
  );
  const area = (f: FormField, rows = 3) => (
    <Textarea
      id={`plugin-${f}`}
      rows={rows}
      value={values[f]}
      placeholder={defaults[f] || 'One per line'}
      onChange={(e) => set(f)(e.target.value)}
    />
  );

  const type = effective(values, defaults, 'accessType') || 'mlflow_model';
  const outType = effective(values, defaults, 'outputType');
  const name = data?.name ?? '';
  const existing = !!data?.existing;
  const placement = data?.defaults.placement;
  const label = (id: string) => graph.components.find((c) => c.id === id)?.name ?? id.split('.').pop();

  const onSave = () => {
    setTouched(true);
    if (!data) return;
    const problems = validateForm(values, defaults);
    if (Object.keys(problems).length) {
      toast.error('Check the highlighted fields');
      return;
    }
    // Auto fill also keeps the example's test hints and I/O (not shown as fields).
    const base =
      autoFilled && data.example
        ? {
            ...data.defaults,
            io: data.example.io ?? data.defaults.io,
            scenarios: data.example.scenarios ?? data.defaults.scenarios,
          }
        : data.defaults;
    const card = cardFromForm(values, base, data.existing);
    save.mutate(
      {
        name,
        card,
        component: data.component,
        reason: existing ? 'plugin updated' : 'plugin configured',
        upstream: standalone ? connection(upstream) : undefined,
        downstream: standalone ? connection(downstream) : undefined,
        copyExampleFiles: autoFilled,
      },
      {
        onSuccess: (res) => {
          const copied = res.files_copied?.length ?? 0;
          toast.success(res.changed || copied ? `Plugin saved: ${card.name}` : 'No changes', {
            description: copied
              ? `${res.path} · ${copied} file${copied === 1 ? '' : 's'} added (data dictionary, docs)`
              : res.changed
                ? `${res.path} · version ${res.version}`
                : undefined,
          });
          onOpenChange(false);
        },
        onError: (e) => toast.error('Could not save the plugin', { description: (e as Error).message }),
      },
    );
  };

  const title = component?.name ?? (data ? data.defaults.name : 'Add a model');
  const description = component
    ? `${component.id} · ${existing ? 'plugin configured' : 'no plugin yet'}`
    : 'A model that is not in the system graph yet';

  return (
    <Sheet
      open={!!target}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      width="w-[min(40rem,100vw)]"
      footer={
        data ? (
          <div className="flex w-full items-center gap-3">
            <span className="mr-auto text-xs text-muted">
              {changed.length
                ? `${changed.length} field${changed.length === 1 ? '' : 's'} differ from the defaults`
                : 'All defaults'}
            </span>
            {component && (
              <Button
                variant="ghost"
                size="sm"
                loading={remove.isPending}
                onClick={() =>
                  remove.mutate(component.id, {
                    onSuccess: () => {
                      toast.success(`Removed ${component.name} from the graph`, {
                        description: component.plugin ? 'Its plugin files stay in the folder.' : undefined,
                      });
                      onOpenChange(false);
                    },
                    onError: (e) => toast.error('Could not remove it', { description: (e as Error).message }),
                  })
                }
              >
                <Trash2 /> Remove
              </Button>
            )}
            {changed.length > 0 && (
              <Button variant="ghost" size="sm" onClick={() => setValues(emptyForm())}>
                <RotateCcw /> Reset
              </Button>
            )}
            <Button size="sm" onClick={onSave} loading={save.isPending}>
              {existing ? 'Save plugin' : 'Create plugin'}
            </Button>
          </div>
        ) : undefined
      }
    >
      <div className="space-y-8">
        {standalone && (
          <Block title="Which model?" hint="The model on the local MLflow server this plugin wraps.">
            <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_12rem]">
              <Field label="MLflow model URI" htmlFor="plugin-new-uri">
                <Input
                  id="plugin-new-uri"
                  value={modelUri}
                  placeholder="models:/sys-002-credit-scorer@champion"
                  onChange={(e) => setModelUri(e.target.value)}
                  className="font-mono text-xs"
                />
              </Field>
              <Field
                label="Plugin folder"
                htmlFor="plugin-new-folder"
                error={folder && !SLUG.test(folder) ? 'Lowercase letters, digits and -' : undefined}
              >
                <Input
                  id="plugin-new-folder"
                  value={folder}
                  placeholder="from the model name"
                  onChange={(e) => setFolder(e.target.value.trim())}
                  className="font-mono text-xs"
                />
              </Field>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                const m = nextExampleModel(graph);
                setModelUri(m.model);
                setFolder(m.folder);
                setUpstream(graph.components[graph.components.length - 1]?.id ?? '');
                setDownstream('');
              }}
            >
              <Wand2 /> Auto fill
            </Button>
            <ConnectionFields
              graph={graph}
              upstream={upstream}
              downstream={downstream}
              onUpstream={setUpstream}
              onDownstream={setDownstream}
            />
            <Button
              variant="secondary"
              size="sm"
              disabled={!modelUri.trim() || (!!folder && !SLUG.test(folder))}
              onClick={() => setLookup({ model: modelUri.trim(), name: folder || undefined })}
            >
              <Boxes /> Load defaults
            </Button>
          </Block>
        )}

        {defaultsQ.isLoading && (
          <div className="space-y-3">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-2/3" />
          </div>
        )}
        {defaultsQ.error && (
          <p className="text-sm text-danger">
            Could not load the defaults: {(defaultsQ.error as Error).message}
          </p>
        )}

        {data && (
          <>
            <MlflowBanner info={data.mlflow} uri={effective(values, defaults, 'uri')} />

            {data.example && (
              <div className="flex flex-wrap items-center gap-3 rounded-xl border border-primary/25 bg-primary/5 px-3.5 py-3 text-sm">
                <Wand2 className="size-4 shrink-0 text-primary" aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className="font-medium">
                    {autoFilled
                      ? 'Filled from the ready-made plugin'
                      : 'A ready-made plugin exists for this model'}
                  </div>
                  <p className="mt-0.5 text-xs text-muted">
                    Expected behaviour, limits and output
                    {data.example_files?.length
                      ? `, plus ${data.example_files.length} file${data.example_files.length === 1 ? '' : 's'} (data dictionary, docs) copied on save`
                      : ''}
                    .
                  </p>
                </div>
                <Button variant={autoFilled ? 'ghost' : 'secondary'} size="sm" onClick={autoFill}>
                  <Wand2 /> Auto fill
                </Button>
              </div>
            )}

            {placement && placement.kind !== 'standalone' && (
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                <Badge tone="neutral">Step {placement.position}</Badge>
                {(placement.upstream ?? []).map((u) => (
                  <span key={u} className="inline-flex items-center gap-2">
                    {label(u)} <ArrowRight className="size-3" aria-hidden />
                  </span>
                ))}
                <span className="font-semibold text-text">{data.defaults.name}</span>
                {(placement.downstream ?? []).map((d) => (
                  <span key={d} className="inline-flex items-center gap-2">
                    <ArrowRight className="size-3" aria-hidden /> {label(d)}
                  </span>
                ))}
              </div>
            )}

            <Block title="Connection" hint="How the audit agent calls the model from the sandbox.">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Name" htmlFor="plugin-name" error={errors.name}>
                  {input('name')}
                </Field>
                <Field label="Access" htmlFor="plugin-accessType">
                  <Select
                    id="plugin-accessType"
                    value={values.accessType || undefined}
                    placeholder={ACCESS_OPTIONS.find((o) => o.value === defaults.accessType)?.label}
                    onValueChange={set('accessType')}
                    options={ACCESS_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                  />
                </Field>
                <Field
                  label="Model URI"
                  htmlFor="plugin-uri"
                  error={errors.uri}
                  hint={type === 'rest' ? 'Kept so the audit pins the exact model version.' : undefined}
                  className="sm:col-span-2"
                >
                  {input('uri', { mono: true })}
                </Field>
                {type === 'rest' && (
                  <Field
                    label="Endpoint"
                    htmlFor="plugin-url"
                    error={errors.url}
                    hint="A /v1/… path goes to the model gateway; or a full https:// URL."
                    className="sm:col-span-2"
                  >
                    {input('url', { mono: true })}
                  </Field>
                )}
                <Field label="Environment" htmlFor="plugin-environment">
                  {input('environment')}
                </Field>
                <Field
                  label="Token (env var)"
                  htmlFor="plugin-secretRef"
                  error={errors.secretRef}
                  hint="Named only; the secret stays in the sandbox's environment."
                >
                  {input('secretRef', { mono: true })}
                </Field>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <Field label="Requests / s" htmlFor="plugin-rps" error={errors.rps}>
                  {input('rps', { type: 'number' })}
                </Field>
                <Field label="Timeout (s)" htmlFor="plugin-timeoutS" error={errors.timeoutS}>
                  {input('timeoutS', { type: 'number' })}
                </Field>
                <Field label="Request budget" htmlFor="plugin-maxRequests" error={errors.maxRequests}>
                  {input('maxRequests', { type: 'number' })}
                </Field>
              </div>
            </Block>

            <Block title="Inputs and output" hint="Read from the model's MLflow signature.">
              {data.mlflow.inputs.length > 0 && (
                <div className="space-y-1.5">
                  <div className="text-xs font-medium text-muted">
                    Input fields ({data.mlflow.inputs.length})
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {data.mlflow.inputs.map((f) => (
                      <span
                        key={f.name}
                        className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-muted/50 px-2 py-0.5 font-mono text-2xs"
                      >
                        {f.name}
                        <span className="text-muted">{f.type}</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Returns" htmlFor="plugin-outputType">
                  <Select
                    id="plugin-outputType"
                    value={values.outputType || undefined}
                    placeholder={
                      OUTPUT_OPTIONS.find((o) => o.value === defaults.outputType)?.label ?? 'Table'
                    }
                    onValueChange={set('outputType')}
                    options={OUTPUT_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                  />
                </Field>
                {outType.endsWith('classification') && (
                  <Field label="Positive label" htmlFor="plugin-positiveLabel">
                    {input('positiveLabel')}
                  </Field>
                )}
                {outType.endsWith('classification') && (
                  <>
                    <Field label="Decision field" htmlFor="plugin-labelField">
                      {input('labelField', { mono: true })}
                    </Field>
                    <Field label="Score field" htmlFor="plugin-scoreField">
                      {input('scoreField', { mono: true })}
                    </Field>
                  </>
                )}
              </div>
            </Block>

            <Block title="Expected behaviour" hint="The agent tests against these. One item per line.">
              <Field label="What it does" htmlFor="plugin-task">
                {area('task', 2)}
              </Field>
              <Field label="Must" htmlFor="plugin-must">
                {area('must')}
              </Field>
              <Field label="Must never" htmlFor="plugin-mustNot">
                {area('mustNot')}
              </Field>
              <Field label="Known limitations" htmlFor="plugin-limitations">
                {area('limitations')}
              </Field>
            </Block>

            {existing && <PluginFiles systemId={systemId} folder={name} />}
            {!existing && (
              <p className="text-xs text-muted">
                Saved as <code className="font-mono">plugins/{name}/plugin.yaml</code>. After saving you can
                add its docs and data dictionary here
                {autoFilled && data.example_files?.length ? ' (Auto fill adds them for you)' : ''}.
              </p>
            )}
          </>
        )}
      </div>
    </Sheet>
  );
}
