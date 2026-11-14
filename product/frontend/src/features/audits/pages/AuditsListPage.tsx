import { motion } from 'framer-motion';
import { ArrowRight, ClipboardCheck } from 'lucide-react';
import { Link } from 'react-router-dom';
import { formatRelative } from '@/shared/lib/format';
import { listItem, staggerList } from '@/shared/lib/motion';
import {
  Card,
  EmptyState,
  ErrorState,
  PageHeader,
  ProgressRing,
  SkeletonCard,
  StatusPill,
} from '@/shared/ui';
import { TraceLink } from '../components/artifact_parts/common';
import { useAudits } from '../hooks/useAudits';
import { STAGES, progress, stageIndex, statusLabel } from '../lib/pipeline';

export function AuditsListPage() {
  const { data, isLoading, error, refetch } = useAudits();

  return (
    <div>
      <PageHeader
        title="Audits"
        description="Agent audit runs: context, scenarios, synthetic data, tests, findings and reports, each step traced in Langfuse."
        icon={<ClipboardCheck />}
      />
      {isLoading && (
        <div className="grid gap-3">
          <SkeletonCard />
          <SkeletonCard />
        </div>
      )}
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {data && data.length === 0 && (
        <EmptyState
          icon={<ClipboardCheck />}
          title="No audits yet"
          description="Start an audit from a system page."
        />
      )}
      {data && data.length > 0 && (
        <motion.div variants={staggerList()} initial="initial" animate="animate" className="grid gap-3">
          {data.map((a) => {
            const i = stageIndex(a.stage);
            const p = progress(a);
            const waiting = a.status === 'waiting_approval';
            return (
              <motion.div key={a.id} variants={listItem}>
                <Link to={`/audits/${encodeURIComponent(a.id)}`} className="block">
                  <Card interactive className="flex items-center gap-4 p-4">
                    <ProgressRing
                      value={p}
                      size={48}
                      tone={a.status === 'done' ? 'success' : waiting ? 'warning' : 'gradient'}
                      label={<span className="text-[11px] font-semibold">{Math.round(p * 100)}%</span>}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs text-muted">{a.systemId}</span>
                        <span className="font-medium">{a.data.systemName ?? a.systemId}</span>
                        <span className="text-muted">·</span>
                        <span>{a.data.title ?? 'Audit'}</span>
                        <StatusPill
                          status={waiting ? 'needs_approval' : a.status}
                          label={statusLabel(a.status)}
                        />
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                        <span>
                          {a.status === 'done'
                            ? 'Finished'
                            : `Step ${i + 1}/${STAGES.length}: ${STAGES[i]?.label ?? a.stage}`}
                        </span>
                        {a.data.kbVersion && <span className="font-mono">kb {a.data.kbVersion}</span>}
                        {a.data.trigger && a.data.trigger !== 'manual' && (
                          <span>trigger: {a.data.trigger}</span>
                        )}
                        <span>updated {formatRelative(a.updatedAt)}</span>
                        <TraceLink traceId={a.data.traceId} />
                      </div>
                    </div>
                    <ArrowRight className="size-4 text-muted" />
                  </Card>
                </Link>
              </motion.div>
            );
          })}
        </motion.div>
      )}
    </div>
  );
}
