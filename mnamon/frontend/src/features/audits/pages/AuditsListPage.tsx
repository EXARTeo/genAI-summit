import { motion } from 'framer-motion';
import { ChevronRight, ClipboardCheck } from 'lucide-react';
import { Link } from 'react-router-dom';
import { formatRelative } from '@/shared/lib/format';
import { listItem, staggerList } from '@/shared/lib/motion';
import { cn } from '@/shared/lib/utils';
import { AgentThinking, Card, EmptyState, ErrorState, PageHeader, Skeleton, StatusPill } from '@/shared/ui';
import { StartAuditMenu } from '@/features/systems/components/StartAuditButton';
import { useAudits } from '../hooks/useAudits';
import { STAGES, progress, stageIndex, statusLabel } from '../lib/pipeline';
import { auditLabel } from '@/shared/lib/labels';

const GRID = 'md:grid-cols-[minmax(0,2fr)_minmax(0,1.6fr)_140px_110px_16px]';

export function AuditsListPage() {
  const { data, isLoading, error, refetch } = useAudits();

  return (
    <div>
      <PageHeader
        title="Audits"
        description="Agent audit runs: context, scenarios, synthetic data, tests, findings and reports."
        actions={<StartAuditMenu />}
      />
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {isLoading && (
        <Card className="divide-y divide-border">
          {Array.from({ length: 3 }, (_, i) => (
            <div key={i} className="flex items-center gap-4 px-4 py-4">
              <div className="flex-1 space-y-1.5">
                <Skeleton className="h-3.5 w-56" />
                <Skeleton className="h-3 w-40" />
              </div>
              <Skeleton className="h-1.5 w-32" />
            </div>
          ))}
        </Card>
      )}
      {data && data.length === 0 && (
        <EmptyState
          icon={<ClipboardCheck />}
          title="No audits yet"
          description="Start an audit of a system: the agent loads its context and plans the tests."
          action={<StartAuditMenu />}
        />
      )}
      {data && data.length > 0 && (
        <Card className="overflow-hidden">
          <div
            className={cn(
              'hidden gap-4 border-b border-border px-4 py-2 text-2xs font-medium text-muted md:grid',
              GRID,
            )}
          >
            <span>Run</span>
            <span>Current step</span>
            <span>Progress</span>
            <span>Updated</span>
            <span />
          </div>
          <motion.ul variants={staggerList()} initial="initial" animate="animate">
            {data.map((a) => {
              const i = stageIndex(a.stage);
              const p = progress(a);
              const waiting = a.status === 'waiting_approval';
              const live = a.status === 'running' || a.status === 'open';
              return (
                <motion.li key={a.id} variants={listItem} className="border-b border-border last:border-b-0">
                  <Link
                    to={`/audits/${encodeURIComponent(a.id)}`}
                    className={cn(
                      'group grid items-center gap-x-4 gap-y-2 px-4 py-3.5 transition-colors hover:bg-surface-muted/50',
                      GRID,
                    )}
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium">
                          {a.data.systemName ?? a.systemId}
                        </span>
                        <span className="truncate text-sm text-muted">{a.data.title ?? 'Audit'}</span>
                      </div>
                      <div className="num mt-0.5 flex items-center gap-2 truncate text-2xs text-muted">
                        <span>{auditLabel(a)}</span>
                        {a.data.kbVersion && <span className="font-mono">kb {a.data.kbVersion}</span>}
                      </div>
                    </div>
                    <div className="min-w-0 text-xs">
                      {live ? (
                        <AgentThinking size="sm" label={STAGES[i]?.label ?? a.stage} />
                      ) : (
                        <span className="flex min-w-0 items-center gap-2">
                          <StatusPill
                            status={waiting ? 'needs_approval' : a.status}
                            label={statusLabel(a.status)}
                          />
                          {waiting && <span className="truncate text-muted">{STAGES[i]?.label}</span>}
                        </span>
                      )}
                      {a.data.trigger && a.data.trigger !== 'manual' && (
                        <div className="mt-1 truncate text-2xs text-muted">Triggered by {a.data.trigger}</div>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="h-1 flex-1 overflow-hidden rounded-full bg-surface-muted">
                        <div
                          className={cn(
                            'h-full rounded-full',
                            waiting ? 'bg-warning' : a.status === 'done' ? 'bg-text/40' : 'bg-primary',
                          )}
                          style={{ width: `${Math.round(p * 100)}%` }}
                        />
                      </div>
                      <span className="num w-9 text-right text-2xs text-muted">
                        {a.status === 'done'
                          ? `${STAGES.length}/${STAGES.length}`
                          : `${i + 1}/${STAGES.length}`}
                      </span>
                    </div>
                    <span className="num text-xs text-muted">{formatRelative(a.updatedAt)}</span>
                    <ChevronRight className="hidden size-4 text-muted opacity-0 transition-opacity group-hover:opacity-100 md:block" />
                  </Link>
                </motion.li>
              );
            })}
          </motion.ul>
        </Card>
      )}
    </div>
  );
}
