import { motion } from 'framer-motion';
import { ArrowRight, ArrowUpCircle, ArrowUpRight, Check, Eye, RotateCcw, Trash2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useState, type ReactNode } from 'react';
import { TraceLink } from '@/features/audits/components/artifact_parts/common';
import { cn } from '@/shared/lib/utils';
import {
  AnimatedNumber,
  Badge,
  Button,
  Input,
  KeyValue,
  StatusPill,
  Timeline,
  toast,
  type TimelineItem,
} from '@/shared/ui';
import { useMemoryAction } from '../hooks/useMemory';
import { STATUS_TONE, allowedActions, scopeLabel, type MemoryAction } from '../lib/memory';
import type { MemoryEntry, MemoryEvent, MemoryStatus } from '../lib/types';

const LIFECYCLE: MemoryStatus[] = ['proposed', 'active', 'stale', 'retired'];

const ACTION_UI: Record<
  MemoryAction,
  { label: string; icon: ReactNode; variant: 'primary' | 'secondary' | 'danger' | 'accent' }
> = {
  approve: { label: 'Approve', icon: <Check />, variant: 'primary' },
  promote: { label: 'Promote org-wide', icon: <ArrowUpCircle />, variant: 'secondary' },
  retire: { label: 'Retire', icon: <Trash2 />, variant: 'secondary' },
  reactivate: { label: 'Re-activate', icon: <RotateCcw />, variant: 'secondary' },
};

const EVENT_TONE: Record<MemoryEvent['action'], TimelineItem['tone']> = {
  create: 'info',
  update: 'primary',
  approve: 'success',
  promote: 'accent',
  retire: 'neutral',
  stale: 'warning',
  read: 'neutral',
  reject: 'danger',
};

export function MemoryDetail({
  entry,
  all,
  compact,
}: {
  entry: MemoryEntry;
  all: MemoryEntry[];
  /** Inside a side sheet: no id heading (the sheet title has it). */
  compact?: boolean;
}) {
  const act = useMemoryAction();
  const [reason, setReason] = useState('');
  const promoted = all.some((e) => e.promotedFrom === entry.id);
  const actions = allowedActions(entry, promoted);
  const reads = entry.history.filter((h) => h.action === 'read');
  const audits = Array.from(new Set(reads.map((h) => h.runId).filter((r): r is string => !!r)));

  const run = (action: MemoryAction) =>
    act.mutate(
      { id: entry.id, action, reason },
      {
        onSuccess: (res) => {
          setReason('');
          toast.success(
            action === 'promote'
              ? `Promotion proposed as ${res.id}`
              : `${entry.id}: ${ACTION_UI[action].label.toLowerCase()}d`,
            {
              description:
                action === 'promote'
                  ? 'The AI Officer approves org-wide memory after a regression check.'
                  : undefined,
            },
          );
        },
        onError: (e) => toast.error('Action failed', { description: (e as Error).message }),
      },
    );

  return (
    <motion.div
      key={entry.id}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.18 }}
      className="space-y-5"
    >
      <div className="flex flex-wrap items-center gap-2">
        {!compact && <h2 className="num mr-1 font-mono text-base font-semibold">{entry.id}</h2>}
        <StatusPill status={entry.status} tone={STATUS_TONE[entry.status]} />
        <Badge>{scopeLabel(entry.scope)}</Badge>
        <Badge>{entry.kind}</Badge>
        <Badge>{entry.reasonCategory.replace(/_/g, ' ')}</Badge>
      </div>

      <div className="overflow-hidden rounded-lg border border-border">
        <div className="px-3.5 py-3">
          <div className="text-2xs font-medium text-muted">The agent proposed</div>
          <div className="mt-0.5 text-sm text-muted line-through decoration-muted/50">{entry.proposed}</div>
        </div>
        <div className="flex items-center gap-2 border-t border-border bg-surface-muted/50 px-3.5 py-3">
          <ArrowRight className="size-3.5 shrink-0 text-primary" />
          <div className="min-w-0">
            <div className="text-2xs font-medium text-muted">
              Corrected by <span className="text-text">{entry.author}</span>
            </div>
            <div className="mt-0.5 text-sm font-medium">{entry.humanDecision}</div>
          </div>
        </div>
      </div>
      <p className="text-sm text-muted">{entry.rationale}</p>

      <div className="grid grid-cols-3 divide-x divide-border rounded-lg border border-border">
        <Stat label="Used in runs" value={entry.usageCount} />
        <Stat label="Logged reads" value={reads.length} icon={<Eye className="size-3" />} />
        <div className="px-3 py-2.5">
          <div className="text-2xs text-muted">Lifecycle</div>
          <div className="mt-1 flex items-center gap-1">
            {LIFECYCLE.map((s) => (
              <span
                key={s}
                title={s}
                className={cn('h-1.5 flex-1 rounded-full', s === entry.status ? 'bg-primary' : 'bg-border')}
              />
            ))}
          </div>
          <div className="mt-1 text-2xs capitalize">{entry.status}</div>
        </div>
      </div>

      {audits.length > 0 && (
        <div>
          <div className="mb-1.5 text-xs font-medium text-muted">Applied in audits</div>
          <div className="flex flex-wrap gap-1.5">
            {audits.map((a) => (
              <Link
                key={a}
                to={`/audits/${encodeURIComponent(a)}`}
                className="num inline-flex h-6 items-center gap-1 rounded-md border border-border px-2 font-mono text-2xs text-muted transition-colors hover:border-text/20 hover:text-text"
              >
                {a}
                <ArrowUpRight className="size-3" />
              </Link>
            ))}
          </div>
        </div>
      )}

      <KeyValue
        items={[
          {
            label: 'Applies to',
            value:
              Object.entries(entry.appliesTo)
                .map(([k, v]) => `${k}: ${v}`)
                .join(' · ') || '–',
            mono: true,
          },
          { label: 'kb_version', value: entry.kbVersion, mono: true },
          { label: 'Approved by', value: entry.approvedBy ?? '– (pending)' },
          { label: 'Promoted from', value: entry.promotedFrom ?? '–', mono: true },
          {
            label: 'Version',
            value: `v${entry.version}${entry.supersedes ? ` (supersedes ${entry.supersedes})` : ''}`,
            mono: true,
          },
          { label: 'Source', value: <TraceLink traceId={entry.sourceTrace} label="Langfuse trace" /> },
        ]}
      />

      {actions.length > 0 && (
        <div className="space-y-2 rounded-lg border border-border bg-surface-muted/40 p-3">
          <Input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason (logged in the ledger)"
            aria-label="Reason"
          />
          <div className="flex flex-wrap gap-2">
            {actions.map((a) => (
              <Button
                key={a}
                size="sm"
                variant={ACTION_UI[a].variant}
                leftIcon={ACTION_UI[a].icon}
                loading={act.isPending && act.variables?.action === a}
                onClick={() => run(a)}
              >
                {ACTION_UI[a].label}
              </Button>
            ))}
          </div>
        </div>
      )}

      <div>
        <div className="mb-2 text-xs font-medium text-muted">History (append-only)</div>
        <Timeline
          items={[...entry.history].reverse().map((h, i) => ({
            id: `${h.at}-${i}`,
            title: h.action,
            description: [h.reason, h.runId && `run ${h.runId}`].filter(Boolean).join(' · ') || undefined,
            at: h.at,
            actor: h.actor,
            tone: EVENT_TONE[h.action],
          }))}
        />
      </div>
    </motion.div>
  );
}

function Stat({ label, value, icon }: { label: string; value: number; icon?: ReactNode }) {
  return (
    <div className="px-3 py-2.5">
      <div className="flex items-center gap-1 text-2xs text-muted">
        {icon}
        {label}
      </div>
      <AnimatedNumber value={value} className="num mt-0.5 block text-lg font-semibold" />
    </div>
  );
}
