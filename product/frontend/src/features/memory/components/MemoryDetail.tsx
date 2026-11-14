import { motion } from 'framer-motion';
import { ArrowRight, ArrowUpCircle, Brain, Check, Eye, RotateCcw, Trash2 } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { TraceLink } from '@/features/audits/components/artifact_parts/common';
import { cn } from '@/shared/lib/utils';
import {
  AnimatedNumber,
  Badge,
  Button,
  Card,
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
  promote: { label: 'Promote to org', icon: <ArrowUpCircle />, variant: 'accent' },
  retire: { label: 'Retire', icon: <Trash2 />, variant: 'danger' },
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

export function MemoryDetail({ entry, all }: { entry: MemoryEntry; all: MemoryEntry[] }) {
  const act = useMemoryAction();
  const [reason, setReason] = useState('');
  const promoted = all.some((e) => e.promotedFrom === entry.id);
  const actions = allowedActions(entry, promoted);
  const reads = entry.history.filter((h) => h.action === 'read').length;

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
      initial={{ opacity: 0, x: 12 }}
      animate={{ opacity: 1, x: 0 }}
      className="space-y-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Brain className="size-5 text-info" />
        <h2 className="font-mono text-lg font-semibold">{entry.id}</h2>
        <StatusPill status={entry.status} tone={STATUS_TONE[entry.status]} />
        <Badge tone={entry.scope === 'org' ? 'accent' : 'primary'}>{scopeLabel(entry.scope)}</Badge>
        <Badge>{entry.kind}</Badge>
        <Badge tone="warning">{entry.reasonCategory}</Badge>
      </div>

      <div className="grid gap-3 sm:grid-cols-[1fr_auto_1fr] sm:items-stretch">
        <Card className="p-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted">Agent proposed</div>
          <div className="mt-1 text-sm line-through decoration-danger/60">{entry.proposed}</div>
        </Card>
        <ArrowRight className="hidden size-5 self-center text-muted sm:block" />
        <Card className="border-success/40 bg-success/5 p-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-success">Human decision</div>
          <div className="mt-1 text-sm font-medium">{entry.humanDecision}</div>
        </Card>
      </div>
      <p className="text-sm text-muted">{entry.rationale}</p>

      <div className="flex items-center gap-1">
        {LIFECYCLE.map((s, i) => (
          <div key={s} className="flex items-center gap-1">
            <span
              className={cn(
                'rounded-full border px-2.5 py-0.5 text-xs',
                s === entry.status
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'border-border text-muted',
              )}
            >
              {s}
            </span>
            {i < LIFECYCLE.length - 1 && <span className="h-px w-3 bg-border" />}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Card className="p-3">
          <div className="text-xs text-muted">Used in runs</div>
          <AnimatedNumber value={entry.usageCount} className="text-2xl font-semibold" />
        </Card>
        <Card className="p-3">
          <div className="flex items-center gap-1 text-xs text-muted">
            <Eye className="size-3" /> Logged reads
          </div>
          <AnimatedNumber value={reads} className="text-2xl font-semibold" />
        </Card>
      </div>

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
          { label: 'Author', value: entry.author },
          { label: 'Approved by', value: entry.approvedBy ?? '– (pending)' },
          { label: 'Promoted from', value: entry.promotedFrom ?? '–', mono: true },
          {
            label: 'Version',
            value: `v${entry.version}${entry.supersedes ? ` (supersedes ${entry.supersedes})` : ''}`,
            mono: true,
          },
        ]}
      />
      <TraceLink traceId={entry.sourceTrace} label="Source trace" />

      {actions.length > 0 && (
        <Card className="space-y-2 p-3">
          <Input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason (logged in the ledger)"
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
        </Card>
      )}

      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">
          History (append-only)
        </h3>
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
