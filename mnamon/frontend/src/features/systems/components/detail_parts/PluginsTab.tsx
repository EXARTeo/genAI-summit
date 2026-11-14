import { motion } from 'framer-motion';
import { CheckCircle2, CircleSlash, Plug, TriangleAlert } from 'lucide-react';
import { useState } from 'react';
import { listItem, staggerList } from '@/shared/lib/motion';
import { cn } from '@/shared/lib/utils';
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  EmptyState,
  ErrorState,
  KeyValue,
  Section,
  SkeletonCard,
} from '@/shared/ui';
import { usePlugins } from '../../hooks/useSystemFolder';
import { ACCESS_LABEL } from '../../lib/styles';
import type { PluginCard } from '../../lib/types';
import { PipelineGraph } from './PipelineGraph';

function List({ items, icon, cls }: { items?: string[]; icon: JSX.Element; cls: string }) {
  if (!items?.length) return null;
  return (
    <ul className="space-y-1">
      {items.map((t) => (
        <li key={t} className="flex items-start gap-2 text-sm">
          <span className={cn('mt-0.5 [&_svg]:size-4', cls)}>{icon}</span>
          <span>{t}</span>
        </li>
      ))}
    </ul>
  );
}

function PluginCardView({
  p,
  selected,
  onSelect,
}: {
  p: PluginCard;
  selected: boolean;
  onSelect: () => void;
}) {
  const access = p.access ?? { type: 'unknown' };
  const exp = p.expected_behaviour ?? { task: '' };
  return (
    <motion.div variants={listItem}>
      <Card
        interactive
        onClick={onSelect}
        className={cn('h-full', selected && 'border-primary/50 ring-2 ring-primary/20')}
      >
        <CardHeader
          icon={<Plug />}
          title={p.name}
          description={<span className="font-mono text-xs">{p.id}</span>}
          actions={<Badge tone="accent">{ACCESS_LABEL[access.type] ?? access.type}</Badge>}
        />
        <CardContent className="space-y-4">
          <KeyValue
            items={[
              {
                label: 'Placement',
                value: `${p.placement?.kind?.replace(/_/g, ' ') ?? '-'}${p.placement?.position ? ` · ${p.placement.position}` : ''}`,
              },
              {
                label: 'Environment',
                value: access.environment && (
                  <Badge tone={access.environment === 'production' ? 'warning' : 'neutral'}>
                    {access.environment}
                  </Badge>
                ),
              },
              { label: 'Target', value: access.uri ?? access.url, mono: true },
              {
                label: 'Limits',
                value:
                  access.limits &&
                  Object.entries(access.limits)
                    .map(([k, v]) => `${k} ${v}`)
                    .join(' · '),
                mono: true,
              },
            ]}
          />
          {p.placement?.pipeline_summary && (
            <p className="rounded-lg bg-surface-muted px-3 py-2 text-xs text-muted">
              {p.placement.pipeline_summary}
            </p>
          )}
          <div>
            <div className="mb-1 text-xs font-medium text-muted">Expected behaviour</div>
            <p className="mb-2 text-sm">{exp.task}</p>
            <div className="space-y-1.5">
              <List items={exp.must} icon={<CheckCircle2 />} cls="text-success" />
              <List items={exp.must_not} icon={<CircleSlash />} cls="text-danger" />
              <List items={exp.known_limitations} icon={<TriangleAlert />} cls="text-warning" />
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}

export function PluginsTab({ systemId }: { systemId: string }) {
  const { plugins, isLoading, error, refetch } = usePlugins(systemId);
  const [selected, setSelected] = useState<string | undefined>();

  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-2">
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }
  if (!plugins.length) {
    return (
      <EmptyState
        icon={<Plug />}
        title="No plugins configured"
        description="A plugin connects the agent to one testable model or endpoint: add plugins/<name>/plugin.yaml in the Folder tab."
      />
    );
  }
  return (
    <div className="space-y-6">
      <Section title="Pipeline placement" description="Where each plugin sits; click a card to highlight it.">
        <PipelineGraph plugins={plugins} highlight={selected ?? plugins[0]?.id} />
      </Section>
      <Section title={`Plugins (${plugins.length})`}>
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
              selected={(selected ?? plugins[0]?.id) === p.id}
              onSelect={() => setSelected(p.id)}
            />
          ))}
        </motion.div>
      </Section>
    </div>
  );
}
