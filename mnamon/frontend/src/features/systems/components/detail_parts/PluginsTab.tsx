import { motion } from 'framer-motion';
import {
  CheckCircle2,
  ChevronRight,
  Network,
  Plug,
  Plus,
  Settings2,
  TriangleAlert,
  User,
  XCircle,
} from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { listItem, staggerList } from '@/shared/lib/motion';
import { cn } from '@/shared/lib/utils';
import { Badge, Button, Card, EmptyState, ErrorState, Section, SkeletonCard, Tooltip } from '@/shared/ui';
import { usePluginGraph } from '../../hooks/usePlugins';
import {
  accessIcon,
  limitFacts,
  outputLabel,
  placementLabel,
  stageRef,
  targetLabel,
  type PluginFact,
  type StageRef,
} from '../../lib/plugins';
import { ACCESS_LABEL } from '../../lib/styles';
import type { GraphComponent, PluginCard } from '../../lib/types';
import { PipelineGraph } from './PipelineGraph';
import { GraphStepDialog } from './GraphStepDialog';
import { PluginDetailsSheet } from './PluginDetailsSheet';
import { PluginEditorSheet, type PluginEditorTarget } from './PluginEditorSheet';

/** One pill in the card's pipeline strip. */
function StagePill({ stage, current, ghost }: { stage?: StageRef; current?: boolean; ghost?: string }) {
  return (
    <span
      title={stage?.label ?? ghost}
      className={cn(
        'inline-flex min-w-0 max-w-[40%] items-center gap-1 rounded-full border px-2.5 py-1 text-xs',
        current
          ? 'shrink-0 border-primary/30 bg-primary/10 font-semibold text-primary'
          : 'border-border text-muted',
        !stage && 'border-dashed',
      )}
    >
      {stage?.human && <User className="size-3 shrink-0" aria-hidden />}
      <span className="truncate">{stage?.label ?? ghost}</span>
    </span>
  );
}

function Connector({ className }: { className?: string }) {
  return <span aria-hidden className={cn('h-px min-w-3 flex-1 bg-border', className)} />;
}

/** upstream → this plugin → downstream, as a 3-node strip. */
function PipelineStrip({ p, plugins }: { p: PluginCard; plugins: PluginCard[] }) {
  const up = p.placement?.upstream ?? [];
  const down = p.placement?.downstream ?? [];
  const extra = (n: number) => (n > 1 ? ` +${n - 1}` : '');
  const upStage = up[0] ? stageRef(up[0], plugins) : undefined;
  const downStage = down[0] ? stageRef(down[0], plugins) : undefined;
  return (
    <div className="flex items-center gap-1.5" aria-label="Pipeline placement">
      <StagePill stage={upStage && { ...upStage, label: upStage.label + extra(up.length) }} ghost="Input" />
      <Connector />
      <StagePill stage={{ id: p.id, label: p.name, human: false }} current />
      <Connector />
      <StagePill
        stage={downStage && { ...downStage, label: downStage.label + extra(down.length) }}
        ghost="Output"
      />
    </div>
  );
}

function Fact({ value, unit, label }: PluginFact) {
  const numeric = /^[\d.,]+k?$/.test(value);
  return (
    <div className="min-w-0">
      <div
        className={cn(
          'flex h-8 items-end truncate leading-tight',
          numeric ? 'font-heading text-2xl tabular-nums' : 'text-sm font-medium',
        )}
      >
        {value}
        {unit && <span className="ml-0.5 text-sm text-muted">{unit}</span>}
      </div>
      <div className="truncate text-2xs text-muted">{label}</div>
    </div>
  );
}

function Count({ n, icon, cls, label }: { n: number; icon: ReactNode; cls: string; label: string }) {
  if (!n) return null;
  return (
    <span className="inline-flex items-center gap-1" title={label}>
      <span className={cn('[&_svg]:size-3.5', cls)}>{icon}</span>
      <span className="tabular-nums">{n}</span>
      <span className="sr-only">{label}</span>
    </span>
  );
}

function PluginCardView({
  p,
  plugins,
  selected,
  onSelect,
  onOpen,
  onConfigure,
}: {
  p: PluginCard;
  plugins: PluginCard[];
  selected: boolean;
  onSelect: () => void;
  onOpen: () => void;
  onConfigure: () => void;
}) {
  const access = p.access ?? { type: 'unknown' };
  const exp = p.expected_behaviour ?? { task: '' };
  const Icon = accessIcon(access.type);
  const target = targetLabel(access);
  const output = outputLabel(p.io);
  const facts: PluginFact[] = [
    ...(output ? [{ value: output, label: 'Returns' }] : []),
    ...limitFacts(access.limits).filter((f) => f.label !== 'Request budget'),
  ].slice(0, 3);

  return (
    <motion.div variants={listItem}>
      <Card
        interactive
        onClick={onSelect}
        className={cn('flex h-full flex-col', selected && 'border-primary/50 ring-2 ring-primary/20')}
      >
        <div className="space-y-5 p-5">
          <div className="flex items-start gap-3.5">
            <div className="grid size-11 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary [&_svg]:size-5">
              <Icon />
            </div>
            <div className="min-w-0 flex-1">
              <h3 className="truncate font-heading text-xl leading-tight">{p.name}</h3>
              <p className="mt-0.5 text-xs text-muted">
                {placementLabel(p.placement)}, {ACCESS_LABEL[access.type] ?? access.type}
              </p>
            </div>
            {access.environment && (
              <Badge tone={access.environment === 'production' ? 'warning' : 'neutral'}>
                {access.environment}
              </Badge>
            )}
          </div>

          {exp.task && <p className="line-clamp-2 text-sm leading-relaxed">{exp.task}</p>}

          <PipelineStrip p={p} plugins={plugins} />

          {target && (
            <Tooltip content={<span className="break-all font-mono">{target.full}</span>}>
              <div className="flex min-w-0 items-center gap-2 rounded-lg bg-surface-muted/60 px-3 py-2">
                <Icon className="size-3.5 shrink-0 text-muted" aria-hidden />
                <code className="truncate whitespace-nowrap font-mono text-xs">{target.short}</code>
              </div>
            </Tooltip>
          )}

          {facts.length > 0 && (
            <div className="grid grid-cols-[1.5fr_1fr_1fr] gap-4">
              {facts.map((f) => (
                <Fact key={f.label} {...f} />
              ))}
            </div>
          )}
        </div>

        <div className="mt-auto flex items-center justify-between gap-3 border-t border-border px-5 py-2.5">
          <div className="flex items-center gap-3 text-xs text-muted">
            <Count n={exp.must?.length ?? 0} icon={<CheckCircle2 />} cls="text-success" label="must" />
            <Count n={exp.must_not?.length ?? 0} icon={<XCircle />} cls="text-danger" label="must never" />
            <Count
              n={exp.known_limitations?.length ?? 0}
              icon={<TriangleAlert />}
              cls="text-warning"
              label="known limitations"
            />
            <span>behaviour checks</span>
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                onConfigure();
              }}
            >
              <Settings2 /> Configure
            </Button>
            <Button
              variant="ghost"
              size="sm"
              rightIcon={<ChevronRight />}
              onClick={(e) => {
                e.stopPropagation();
                onSelect();
                onOpen();
              }}
            >
              Details
            </Button>
          </div>
        </div>
      </Card>
    </motion.div>
  );
}

export function PluginsTab({ systemId }: { systemId: string }) {
  const { data: graph, isLoading, error, refetch } = usePluginGraph(systemId);
  const [selected, setSelected] = useState<string | undefined>();
  const [openId, setOpenId] = useState<string | undefined>();
  const [editing, setEditing] = useState<PluginEditorTarget | null>(null);
  const [step, setStep] = useState<{ component: GraphComponent | null } | null>(null);

  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (isLoading || !graph) {
    return (
      <div className="space-y-4">
        <SkeletonCard />
        <div className="grid gap-4 md:grid-cols-2">
          <SkeletonCard />
          <SkeletonCard />
        </div>
      </div>
    );
  }

  const entries = Object.entries(graph.plugins);
  const plugins: PluginCard[] = entries.map(([folder, card]) => ({
    ...card,
    id: card.id ?? `${systemId}.${folder}`,
    name: card.name ?? folder,
  }));
  /** The graph component a plugin wraps (by its id, else by its folder). */
  const componentFor = (p: PluginCard): GraphComponent | null => {
    const folder = entries.find(([f, card]) => (card.id ?? `${systemId}.${f}`) === p.id)?.[0];
    return (
      graph.components.find((c) => c.id === p.id) ??
      graph.components.find((c) => !!folder && c.plugin === folder) ??
      null
    );
  };
  const configure = (c: GraphComponent | null) => {
    if (c) setSelected(c.id);
    setEditing({ component: c });
  };
  const missing = graph.components.filter((c) => c.testable && !c.configured).length;
  const current = selected ?? plugins[0]?.id;
  const opened = plugins.find((p) => p.id === openId);
  const onNode = (c: GraphComponent) => (c.testable ? configure(c) : setStep({ component: c }));
  const addButton = (
    <div className="flex items-center gap-2">
      <Button variant="secondary" size="sm" onClick={() => setStep({ component: null })}>
        <Network /> Add a step
      </Button>
      <Button size="sm" onClick={() => configure(null)}>
        <Plus /> Add a model
      </Button>
    </div>
  );

  return (
    <div className="space-y-6">
      {graph.components.length === 0 && (
        <Section title="System graph" actions={addButton}>
          <EmptyState
            icon={<Network />}
            title="No pipeline yet"
            description="This system was registered with its documents only. Add its models and the steps around them (where the data comes from, who reviews the output); each model then gets a plugin the audit agent calls."
          />
        </Section>
      )}
      {graph.components.length > 0 && (
        <Section
          title="System graph"
          description={
            missing
              ? `Click a model to configure its plugin. ${missing} model${missing === 1 ? ' has' : 's have'} no plugin yet.`
              : 'Click a model to configure its plugin: how the audit agent calls it.'
          }
          actions={addButton}
        >
          <PipelineGraph graph={graph} selected={current} onSelect={onNode} />
        </Section>
      )}

      {plugins.length === 0 ? (
        <EmptyState
          icon={<Plug />}
          title="No plugins configured"
          description="A plugin is the wrapper around one model: how the audit agent reaches it, what it returns and how it must behave. Click a model in the graph, or add one."
        />
      ) : (
        <Section
          title={
            <span className="flex items-center gap-2">
              Plugins
              <Badge tone="primary" className="rounded-full px-2">
                {plugins.length}
              </Badge>
            </span>
          }
          description="Each plugin wraps one model the agent can test. An audit tests one plugin."
        >
          <motion.div
            variants={staggerList()}
            initial="initial"
            animate="animate"
            className="grid gap-4 md:grid-cols-2"
          >
            {plugins.map((p) => (
              <PluginCardView
                key={p.id}
                p={p}
                plugins={plugins}
                selected={current === p.id}
                onSelect={() => setSelected(p.id)}
                onOpen={() => setOpenId(p.id)}
                onConfigure={() => configure(componentFor(p))}
              />
            ))}
          </motion.div>
        </Section>
      )}
      {opened && (
        <PluginDetailsSheet
          plugin={opened}
          open={!!opened}
          onOpenChange={(o) => !o && setOpenId(undefined)}
          onConfigure={() => {
            setOpenId(undefined);
            configure(componentFor(opened));
          }}
        />
      )}
      <GraphStepDialog
        systemId={systemId}
        graph={graph}
        open={!!step}
        component={step?.component}
        onOpenChange={(o) => !o && setStep(null)}
      />
      <PluginEditorSheet
        systemId={systemId}
        graph={graph}
        target={editing}
        onOpenChange={(o) => !o && setEditing(null)}
      />
    </div>
  );
}
