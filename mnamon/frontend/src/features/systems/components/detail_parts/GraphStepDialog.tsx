import { Building2, Cpu, Trash2, User } from 'lucide-react';
import { useEffect, useState } from 'react';
import { cn } from '@/shared/lib/utils';
import { Button, Dialog, Field, Input, Select, toast } from '@/shared/ui';
import type { ComponentKind } from '../../handlers/systems';
import { useAddComponent, useRemoveComponent } from '../../hooks/usePlugins';
import type { GraphComponent, PluginGraph } from '../../lib/types';

const NONE = '__none__';

const KINDS: { value: ComponentKind; label: string; hint: string; icon: typeof Cpu }[] = [
  { value: 'ml_model', label: 'Model', hint: 'An ML model the agent can test (gets a plugin)', icon: Cpu },
  { value: 'upstream_system', label: 'Upstream system', hint: 'Feeds data in; not tested', icon: Building2 },
  { value: 'human_review', label: 'Human step', hint: 'A person reviews or decides; not tested', icon: User },
];

/** "Comes after" / "Goes to" pickers over the graph's boxes. */
export function ConnectionFields({
  graph,
  upstream,
  downstream,
  onUpstream,
  onDownstream,
  exclude,
}: {
  graph: PluginGraph;
  upstream: string;
  downstream: string;
  onUpstream: (v: string) => void;
  onDownstream: (v: string) => void;
  exclude?: string;
}) {
  const options = [
    { value: NONE, label: 'Nothing' },
    ...graph.components.filter((c) => c.id !== exclude).map((c) => ({ value: c.id, label: c.name })),
  ];
  if (!graph.components.length) return null;
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="Comes after" htmlFor="step-upstream" hint="Where its input comes from.">
        <Select id="step-upstream" value={upstream || NONE} onValueChange={onUpstream} options={options} />
      </Field>
      <Field label="Goes to" htmlFor="step-downstream" hint="Who receives its output.">
        <Select
          id="step-downstream"
          value={downstream || NONE}
          onValueChange={onDownstream}
          options={options}
        />
      </Field>
    </div>
  );
}

export const connection = (v: string) => (v && v !== NONE ? [v] : []);

/**
 * Add a box to the system graph, or (with `component`) look at a non-model box and remove it.
 * A model added here shows with a dashed border until its plugin is configured.
 */
export function GraphStepDialog({
  systemId,
  graph,
  open,
  component,
  onOpenChange,
}: {
  systemId: string;
  graph: PluginGraph;
  open: boolean;
  component?: GraphComponent | null;
  onOpenChange: (open: boolean) => void;
}) {
  const add = useAddComponent(systemId);
  const remove = useRemoveComponent(systemId);
  const [name, setName] = useState('');
  const [kind, setKind] = useState<ComponentKind>('ml_model');
  const [model, setModel] = useState('');
  const [upstream, setUpstream] = useState('');
  const [downstream, setDownstream] = useState('');

  useEffect(() => {
    if (!open) {
      setName('');
      setKind('ml_model');
      setModel('');
      setUpstream('');
      setDownstream('');
    }
  }, [open]);

  if (component) {
    const neighbours = graph.edges
      .filter((e) => e.source === component.id || e.target === component.id)
      .map((e) => (e.source === component.id ? e.target : e.source));
    return (
      <Dialog
        open={open}
        onOpenChange={onOpenChange}
        title={component.name}
        description={component.id}
        size="sm"
        footer={
          <>
            <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
              Close
            </Button>
            <Button
              variant="danger"
              size="sm"
              loading={remove.isPending}
              onClick={() =>
                remove.mutate(component.id, {
                  onSuccess: () => {
                    toast.success(`Removed ${component.name} from the graph`);
                    onOpenChange(false);
                  },
                  onError: (e) => toast.error('Could not remove it', { description: (e as Error).message }),
                })
              }
            >
              <Trash2 /> Remove from graph
            </Button>
          </>
        }
      >
        <div className="space-y-2 text-sm">
          <p className="text-muted">
            {component.note ||
              (component.testable
                ? 'A model of this system.'
                : 'Part of the pipeline the audit agent does not call.')}
          </p>
          {neighbours.length > 0 && (
            <p className="text-xs text-muted">
              Removing it also removes its {neighbours.length} connection{neighbours.length === 1 ? '' : 's'}.
              {component.plugin && ' Its plugin files stay in the folder.'}
            </p>
          )}
        </div>
      </Dialog>
    );
  }

  const modelOk = !model || /^models:\/[^@/]+(@[\w-]+|\/\d+)?$/.test(model.trim());
  const submit = () => {
    if (!name.trim() || !modelOk) return;
    add.mutate(
      {
        name: name.trim(),
        kind,
        model: kind === 'ml_model' && model.trim() ? model.trim() : undefined,
        upstream: connection(upstream),
        downstream: connection(downstream),
      },
      {
        onSuccess: () => {
          toast.success(`Added ${name.trim()} to the graph`, {
            description: kind === 'ml_model' ? 'Click it to configure its plugin.' : undefined,
          });
          onOpenChange(false);
        },
        onError: (e) => toast.error('Could not add the step', { description: (e as Error).message }),
      },
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Add a step to the system"
      description="Build the pipeline the model sits in. Saved in architecture.yaml."
      size="md"
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button size="sm" onClick={submit} loading={add.isPending} disabled={!name.trim() || !modelOk}>
            Add step
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Kind of step">
          {KINDS.map((k) => {
            const Icon = k.icon;
            const active = kind === k.value;
            return (
              <button
                key={k.value}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => setKind(k.value)}
                className={cn(
                  'flex flex-col items-start gap-2 rounded-xl border p-3 text-left transition-[border-color,box-shadow] duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  active
                    ? 'border-primary/60 bg-primary/5 ring-2 ring-primary/15'
                    : 'border-border hover:border-primary/30',
                )}
              >
                <span
                  className={cn(
                    'grid size-8 place-items-center rounded-lg [&_svg]:size-4',
                    active ? 'bg-primary/10 text-primary' : 'bg-surface-muted text-muted',
                  )}
                >
                  <Icon />
                </span>
                <span className="text-sm font-semibold leading-tight">{k.label}</span>
                <span className="text-2xs leading-snug text-muted">{k.hint}</span>
              </button>
            );
          })}
        </div>
        <Field label="Name" htmlFor="step-name">
          <Input
            id="step-name"
            value={name}
            autoFocus
            placeholder={
              kind === 'ml_model'
                ? 'Credit scorer'
                : kind === 'human_review'
                  ? 'Credit officer'
                  : 'Loan origination'
            }
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        {kind === 'ml_model' && (
          <Field
            label="MLflow model"
            htmlFor="step-model"
            error={!modelOk ? 'models:/<name>@<alias> or models:/<name>/<version>' : undefined}
            hint="Optional now; the plugin form fills its defaults from it."
          >
            <Input
              id="step-model"
              value={model}
              placeholder="models:/sys-002-credit-scorer@champion"
              onChange={(e) => setModel(e.target.value)}
              className="font-mono text-xs"
            />
          </Field>
        )}
        <ConnectionFields
          graph={graph}
          upstream={upstream}
          downstream={downstream}
          onUpstream={setUpstream}
          onDownstream={setDownstream}
        />
      </div>
    </Dialog>
  );
}
