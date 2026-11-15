import { motion } from 'framer-motion';
import { ArrowUpRight, Hand, Scale } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ApprovalDrawer } from '@/features/approvals/components/ApprovalDrawer';
import { useOpenGates } from '@/features/approvals/hooks/useApprovals';
import type { OpenGate } from '@/features/approvals/lib/approvals';
import { VerdictPill } from '@/features/audits/components/artifact_parts/common';
import { useAudit, useAuditFindings, useAudits } from '@/features/audits/hooks/useAudits';
import { STAGES, progress, stageIndex } from '@/features/audits/lib/pipeline';
import { TONE_CLASSES, verdictStyle } from '@/features/audits/lib/styling';
import { articleOf, panelFindings, sortFindings, titleOf } from '@/features/audits/lib/findings';
import type { Audit } from '@/features/audits/lib/types';
import { useRegChanges } from '@/features/regulation/hooks/useRegulation';
import { useSystems } from '@/features/systems/hooks/useSystems';
import { systemRoutes } from '@/features/systems/lib/routes';
import { riskMeta } from '@/features/systems/lib/styles';
import { formatRelative } from '@/shared/lib/format';
import { listItem, staggerList } from '@/shared/lib/motion';
import { cn } from '@/shared/lib/utils';
import { AgentThinking, Badge, Button, Card, Skeleton } from '@/shared/ui';

const isLive = (a: Audit) => a.status === 'running' || a.status === 'open';

/** Landing page: one glance = what needs me now. */
export function HomePage() {
  const audits = useAudits();
  const { gates, isLoading: gatesLoading } = useOpenGates();
  const systems = useSystems();
  const changes = useRegChanges();
  const [gate, setGate] = useState<OpenGate | null>(null);

  const live = (audits.data ?? []).filter(isLive);
  const lastDone = (audits.data ?? [])
    .filter((a) => a.status === 'done')
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))[0];
  const latestChange = [...(changes.data ?? [])].sort((a, b) => b.detectedAt.localeCompare(a.detectedAt))[0];
  const atRisk = (systems.data ?? []).filter(
    (s) => (s.data.last_audit?.findings?.gaps ?? 0) > 0 || s.data.risk_class === 'high_risk',
  );

  const hour = new Date().getHours();
  const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  const headline =
    gates.length > 0
      ? `${gates.length} decision${gates.length > 1 ? 's' : ''} waiting for you`
      : live.length > 0
        ? `${live.length} audit${live.length > 1 ? 's' : ''} running, nothing needs you`
        : 'All clear';

  return (
    <div className="space-y-8">
      <header>
        <p className="text-sm text-muted">{greeting}</p>
        <h1 className="mt-0.5 text-2xl font-semibold tracking-tight sm:text-3xl">{headline}</h1>
      </header>

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        {/* Needs you */}
        <Panel
          title="Waiting for you"
          count={gates.length}
          tone="warning"
          action={
            <Link to="/audits" className="text-xs text-muted hover:text-text">
              All audits
            </Link>
          }
        >
          {gatesLoading ? (
            <RowsSkeleton />
          ) : gates.length === 0 ? (
            <Empty>Nothing is waiting for you. Agents pause here when they need a human.</Empty>
          ) : (
            <motion.ul variants={staggerList()} initial="initial" animate="animate">
              {gates.map((g) => (
                <motion.li
                  key={`${g.auditId}-${g.gate}`}
                  variants={listItem}
                  className="flex items-center gap-3 border-t border-border px-4 py-3 first:border-t-0"
                >
                  <span className="grid size-7 shrink-0 place-items-center rounded-md bg-warning/10 text-warning">
                    <Hand className="size-3.5" />
                  </span>
                  <Link
                    to={`/audits/${encodeURIComponent(g.auditId)}?step=${encodeURIComponent(g.stageId)}`}
                    className="min-w-0 flex-1 rounded-sm hover:underline"
                  >
                    <div className="truncate text-sm font-medium">{g.label}</div>
                    <div className="truncate text-xs text-muted">
                      {g.systemName} · {g.auditTitle} · waiting {formatRelative(g.waitingSince)}
                    </div>
                  </Link>
                  <Button size="sm" variant="warning" onClick={() => setGate(g)}>
                    Review
                  </Button>
                </motion.li>
              ))}
            </motion.ul>
          )}
        </Panel>

        {/* Live audits */}
        <Panel
          title="Agents at work"
          count={live.length}
          tone="primary"
          action={
            <Link to="/audits" className="text-xs text-muted hover:text-text">
              All audits
            </Link>
          }
        >
          {audits.isLoading ? (
            <RowsSkeleton />
          ) : live.length === 0 ? (
            <Empty>No audit is running right now.</Empty>
          ) : (
            <ul>
              {live.map((a) => {
                const i = stageIndex(a.stage);
                return (
                  <li key={a.id} className="border-t border-border first:border-t-0">
                    <Link
                      to={`/audits/${encodeURIComponent(a.id)}`}
                      className="block px-4 py-3 transition-colors hover:bg-surface-muted/50"
                    >
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium">
                          {a.data.systemName ?? a.systemId}
                        </span>
                        <span className="truncate text-xs text-muted">{a.data.title}</span>
                        <span className="num ml-auto text-xs text-muted">
                          {i + 1}/{STAGES.length}
                        </span>
                      </div>
                      <div className="mt-2 flex items-center gap-3">
                        <AgentThinking
                          size="sm"
                          label={STAGES[i]?.label ?? a.stage}
                          className="min-w-0 flex-1"
                        />
                      </div>
                      <Progress value={progress(a)} />
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <RecentFindings auditId={lastDone?.id} />

        <div className="space-y-4">
          <Panel
            title="Systems at risk"
            count={atRisk.length}
            action={
              <Link to="/systems" className="text-xs text-muted hover:text-text">
                All systems
              </Link>
            }
          >
            {systems.isLoading ? (
              <RowsSkeleton />
            ) : atRisk.length === 0 ? (
              <Empty>No open gaps.</Empty>
            ) : (
              <ul>
                {atRisk.slice(0, 4).map((s) => {
                  const gaps = s.data.last_audit?.findings?.gaps ?? 0;
                  return (
                    <li key={s.id} className="border-t border-border first:border-t-0">
                      <Link
                        to={systemRoutes.detail(s.id)}
                        className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-surface-muted/50"
                      >
                        <span className="num w-14 shrink-0 font-mono text-2xs text-muted">{s.id}</span>
                        <span className="min-w-0 flex-1 truncate text-sm">{s.name}</span>
                        <span className="text-2xs text-muted">{riskMeta(s.data.risk_class).label}</span>
                        <span
                          className={cn(
                            'num w-14 text-right text-xs font-medium',
                            gaps > 0 ? 'text-danger' : 'text-muted',
                          )}
                        >
                          {gaps > 0 ? `${gaps} gap${gaps > 1 ? 's' : ''}` : 'no gaps'}
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>

          <Panel
            title="Latest regulation change"
            action={
              <Link to="/regulation" className="text-xs text-muted hover:text-text">
                Regulation
              </Link>
            }
          >
            {changes.isLoading ? (
              <RowsSkeleton rows={1} />
            ) : !latestChange ? (
              <Empty>No changes detected.</Empty>
            ) : (
              <Link to="/regulation" className="block px-4 py-3 transition-colors hover:bg-surface-muted/50">
                <div className="flex items-center gap-2 text-xs text-muted">
                  <Scale className="size-3.5" />
                  <span className="num font-mono">{latestChange.id}</span>
                  <span>· {formatRelative(latestChange.detectedAt)}</span>
                  <Badge
                    className="ml-auto"
                    tone={latestChange.status === 'proposed' ? 'warning' : 'neutral'}
                  >
                    {latestChange.status}
                  </Badge>
                </div>
                <div className="mt-1 text-sm font-medium">{latestChange.title}</div>
                <div className="mt-0.5 line-clamp-2 text-xs text-muted">{latestChange.summary}</div>
                {latestChange.affected.length > 0 && (
                  <div className="mt-2 text-xs text-muted">
                    Affects {latestChange.affected.map((a) => a.systemId).join(', ')}
                  </div>
                )}
              </Link>
            )}
          </Panel>
        </div>
      </div>

      <ApprovalDrawer
        auditId={gate?.auditId ?? ''}
        gate={gate?.gate ?? null}
        open={gate != null}
        onOpenChange={(o) => !o && setGate(null)}
      />
    </div>
  );
}

function RecentFindings({ auditId }: { auditId?: string }) {
  const { data, isLoading } = useAudit(auditId);
  const sealed = useAuditFindings(auditId);
  // Sealed findings first; older audits fall back to their finding artifacts.
  const findings = data
    ? sortFindings(panelFindings(sealed.data, data.artifacts, data.id, data.systemId)).slice(0, 6)
    : [];
  return (
    <Panel
      title="Recent findings"
      action={
        data && (
          <Link
            to={`/audits/${encodeURIComponent(data.id)}?view=findings`}
            className="inline-flex items-center gap-1 text-xs text-muted hover:text-text"
          >
            {data.data.systemName} · {data.data.title} <ArrowUpRight className="size-3" />
          </Link>
        )
      }
    >
      {isLoading || (!data && auditId) ? (
        <RowsSkeleton rows={4} />
      ) : findings.length === 0 ? (
        <Empty>No findings yet. They appear when an audit finishes.</Empty>
      ) : (
        <ul>
          {findings.map((f) => {
            const tone = verdictStyle(f.verdict).tone;
            return (
              <li key={f.id} className="border-t border-border first:border-t-0">
                <Link
                  to={`/audits/${encodeURIComponent(data!.id)}?view=findings`}
                  className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-surface-muted/50"
                >
                  <span className={cn('h-8 w-0.5 shrink-0 rounded-full', TONE_CLASSES[tone].bg)} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">
                      {[articleOf(f), titleOf(f)].filter(Boolean).join(' · ') || f.obligation_id}
                    </div>
                    <div className="num flex min-w-0 items-center gap-1.5 text-2xs text-muted">
                      <span className="truncate font-mono">{f.obligation_id}</span>
                      {f.gap_id && <span className="shrink-0">· {f.gap_id}</span>}
                    </div>
                  </div>
                  <VerdictPill verdict={f.verdict} />
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

function Panel({
  title,
  count,
  tone,
  action,
  children,
}: {
  title: string;
  count?: number;
  tone?: 'warning' | 'primary';
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <h2 className="text-sm font-semibold">{title}</h2>
        {count != null && count > 0 && (
          <span
            className={cn(
              'num rounded-full px-1.5 text-2xs font-semibold leading-[18px]',
              tone === 'warning'
                ? 'bg-warning/15 text-warning'
                : tone === 'primary'
                  ? 'bg-primary/15 text-primary'
                  : 'bg-surface-muted text-muted',
            )}
          >
            {count}
          </span>
        )}
        <div className="ml-auto">{action}</div>
      </div>
      {children}
    </Card>
  );
}

function Progress({ value }: { value: number }) {
  return (
    <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-surface-muted">
      <motion.div
        className="h-full rounded-full bg-primary"
        initial={{ width: 0 }}
        animate={{ width: `${Math.round(value * 100)}%` }}
        transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      />
    </div>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="px-4 py-8 text-center text-sm text-muted">{children}</div>;
}

function RowsSkeleton({ rows = 2 }: { rows?: number }) {
  return (
    <div className="space-y-3 p-4">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="size-7 rounded-md" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-3 w-2/3" />
            <Skeleton className="h-2.5 w-1/3" />
          </div>
        </div>
      ))}
    </div>
  );
}
