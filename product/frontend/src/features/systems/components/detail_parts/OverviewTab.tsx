import { motion } from 'framer-motion';
import { Activity, Gauge, Scale, ShieldCheck, Users } from 'lucide-react';
import { formatRelative } from '@/shared/lib/format';
import { listItem, staggerList } from '@/shared/lib/motion';
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  EmptyState,
  GlowCard,
  KeyValue,
  ProgressRing,
  StatusPill,
  Timeline,
} from '@/shared/ui';
import { useFileEvents } from '../../hooks/useSystems';
import type { System } from '../../lib/types';

function Pills({ items, tone }: { items?: string[]; tone?: 'warning' | 'primary' }) {
  if (!items?.length) return <span className="text-muted">None declared</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {items.map((i) => (
        <Badge key={i} tone={tone}>
          {i}
        </Badge>
      ))}
    </span>
  );
}

function Thresholds({ entries }: { entries?: Record<string, string> }) {
  const list = Object.entries(entries ?? {});
  if (!list.length) return <EmptyState compact title="No thresholds" />;
  return (
    <ul className="divide-y divide-border">
      {list.map(([k, v]) => (
        <li key={k} className="flex items-center justify-between gap-3 py-2 text-sm">
          <span className="font-mono text-[13px]">{k}</span>
          <span className="rounded-md bg-surface-muted px-2 py-0.5 font-mono text-xs">{v}</span>
        </li>
      ))}
    </ul>
  );
}

export function OverviewTab({ system }: { system: System }) {
  const c = system.data;
  const audit = c.last_audit;
  const events = useFileEvents(system.id);
  const f = audit?.findings;
  const total = f ? f.gaps + f.supports + f.inconclusive : 0;

  return (
    <motion.div
      variants={staggerList()}
      initial="initial"
      animate="animate"
      className="grid gap-4 lg:grid-cols-3"
    >
      <motion.div variants={listItem} className="lg:col-span-2">
        <Card className="h-full">
          <CardHeader
            icon={<ShieldCheck />}
            title="System card"
            description={`card_version ${c.card_version ?? 1}`}
          />
          <CardContent>
            <KeyValue
              items={[
                { label: 'Organisation', value: c.organisation },
                { label: 'AI Act role', value: c.role && <Badge tone="primary">{c.role}</Badge> },
                { label: 'Legal basis', value: c.annex_basis, mono: true },
                {
                  label: 'Deployment',
                  value: c.deployment && (
                    <span className="flex flex-wrap items-center gap-1.5">
                      {c.deployment.status && <StatusPill status={c.deployment.status} />}
                      <span>
                        {c.deployment.countries?.join(', ')} · since {c.deployment.since}
                      </span>
                    </span>
                  ),
                },
                { label: 'Users', value: c.deployment?.users },
                { label: 'Affected persons', value: c.affected_persons },
                { label: 'Human oversight', value: c.human_oversight },
                { label: 'Components', value: <Pills items={c.components} tone="primary" /> },
                { label: 'Protected attributes', value: <Pills items={c.protected_attributes} /> },
                { label: 'Known proxies', value: <Pills items={c.known_proxies} tone="warning" /> },
              ]}
            />
          </CardContent>
        </Card>
      </motion.div>

      <motion.div variants={listItem}>
        <GlowCard
          active={audit?.status === 'running' || audit?.status === 'awaiting_approval'}
          className="h-full"
        >
          <CardHeader
            icon={<Activity />}
            title="Last audit"
            description={audit ? `${audit.id} · ${formatRelative(audit.at)}` : 'Never audited'}
          />
          <CardContent>
            {audit ? (
              <div className="flex items-center gap-5">
                <ProgressRing
                  size={88}
                  stroke={7}
                  value={total ? f!.supports / total : audit.status === 'running' ? 0.35 : 0}
                  label={total ? `${f!.supports}/${total}` : '…'}
                />
                <div className="space-y-2 text-sm">
                  <StatusPill status={audit.status} />
                  {f && (
                    <ul className="space-y-1 text-muted">
                      <li>
                        <span className="font-semibold text-success">{f.supports}</span> support compliance
                      </li>
                      <li>
                        <span className="font-semibold text-danger">{f.gaps}</span> indicate a gap
                      </li>
                      <li>
                        <span className="font-semibold text-warning">{f.inconclusive}</span> inconclusive
                      </li>
                    </ul>
                  )}
                </div>
              </div>
            ) : (
              <EmptyState
                compact
                icon={<Activity />}
                title="No audit yet"
                description="Run the engineer pipeline to get findings."
              />
            )}
          </CardContent>
        </GlowCard>
      </motion.div>

      <motion.div variants={listItem}>
        <Card className="h-full">
          <CardHeader icon={<Gauge />} title="Declared metrics" description="What the provider claims" />
          <CardContent>
            <Thresholds entries={c.declared_metrics} />
          </CardContent>
        </Card>
      </motion.div>

      <motion.div variants={listItem}>
        <Card className="h-full">
          <CardHeader
            icon={<Scale />}
            title="Organisation thresholds"
            description="Internal policy, not legal limits: the AI Act sets no numbers."
          />
          <CardContent>
            <Thresholds entries={c.org_thresholds} />
          </CardContent>
        </Card>
      </motion.div>

      <motion.div variants={listItem}>
        <Card className="h-full">
          <CardHeader icon={<Users />} title="Folder activity" description="Append-only audit ledger" />
          <CardContent className="max-h-80 overflow-y-auto">
            {events.data?.length ? (
              <Timeline
                items={events.data.slice(0, 8).map((e) => ({
                  id: String(e.id),
                  title: <span className="font-mono text-xs">{e.path}</span>,
                  description: `${e.action}${e.version ? ` v${e.version}` : ''}${e.reason ? ` · ${e.reason}` : ''}`,
                  actor: e.actor,
                  at: e.at,
                  tone: e.actor.startsWith('agent') ? 'accent' : e.action === 'delete' ? 'danger' : 'primary',
                }))}
              />
            ) : (
              <EmptyState compact title="No activity yet" />
            )}
          </CardContent>
        </Card>
      </motion.div>
    </motion.div>
  );
}
