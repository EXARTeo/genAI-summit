import { motion } from 'framer-motion';
import { Activity, ArrowUpRight, Gauge, Scale, ShieldCheck, Users } from 'lucide-react';
import { Link } from 'react-router-dom';
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
  StatusPill,
  Timeline,
} from '@/shared/ui';
import { useFileEvents } from '../../hooks/useSystems';
import type { System } from '../../lib/types';
import { actorLabel } from '@/shared/lib/labels';

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
        <GlowCard active={audit?.status === 'running'} className="h-full">
          <CardHeader
            icon={<Activity />}
            title="Last audit"
            description={audit ? `Started ${formatRelative(audit.at)}` : 'Never audited'}
          />
          <CardContent>
            {audit ? (
              <div className="space-y-4">
                <StatusPill status={audit.status} />
                {f && total > 0 && (
                  <>
                    <div className="flex h-2 gap-0.5 overflow-hidden rounded-full" aria-hidden>
                      <span className="bg-danger" style={{ flex: f.gaps }} />
                      <span className="bg-warning" style={{ flex: f.inconclusive }} />
                      <span className="bg-success" style={{ flex: f.supports }} />
                    </div>
                    <dl className="num grid grid-cols-3 gap-2">
                      {(
                        [
                          ['Gaps', f.gaps, 'text-danger'],
                          ['Inconclusive', f.inconclusive, 'text-warning'],
                          ['Supports', f.supports, 'text-success'],
                        ] as const
                      ).map(([label, n, tone]) => (
                        <div key={label}>
                          <dt className="text-2xs text-muted">{label}</dt>
                          <dd className={`text-xl font-semibold ${n > 0 ? tone : ''}`}>{n}</dd>
                        </div>
                      ))}
                    </dl>
                  </>
                )}
                <Link
                  to="/audits"
                  className="inline-flex items-center gap-1 text-xs text-muted hover:text-text"
                >
                  See audits <ArrowUpRight className="size-3" />
                </Link>
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
                  actor: actorLabel(e.actor),
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
