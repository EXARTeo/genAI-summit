/**
 * The approval takeover (magenticx `HitlInputTakeover.tsx`): while the run is paused on an
 * approval it replaces the composer, where the user is already looking. A batched interrupt (the
 * agent gated several tool calls at once) is a deck: decide one card at a time, every decision is
 * sent together after the last (LangChain resolves the batch atomically). Reject takes an
 * optional reason the agent reads.
 */
import { AnimatePresence, motion } from 'framer-motion';
import { Check, ChevronDown, ShieldAlert, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { cn } from '@/shared/lib/utils';
import { Button } from '@/shared/ui';
import {
  approvalHeadline,
  formatArgs,
  hitlActionRequests,
  humanizeToolName,
  isGenericHitlDescription,
} from '../lib/hitl';
import type { Approval } from '../lib/timeline';
import type { ResumeDecision } from '../lib/types';

function ArgsView({ args }: { args: unknown }) {
  const [open, setOpen] = useState(false);
  const entries =
    args && typeof args === 'object' && !Array.isArray(args)
      ? Object.entries(args as Record<string, unknown>)
      : [];
  const simple = entries.filter(([, v]) => typeof v !== 'object' || v === null).slice(0, 6);
  return (
    <div className="space-y-1.5">
      {simple.length > 0 && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          {simple.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-muted">{k}</dt>
              <dd className="truncate font-mono text-2xs leading-4">{String(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {args !== undefined && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex items-center gap-1 text-2xs text-muted hover:text-text"
        >
          <ChevronDown className={cn('size-3 transition-transform', open && 'rotate-180')} />{' '}
          {open ? 'Hide' : 'Show'} full arguments
        </button>
      )}
      {open && (
        <pre className="max-h-40 overflow-auto rounded-md bg-surface-muted p-2 font-mono text-2xs leading-relaxed">
          {formatArgs(args)}
        </pre>
      )}
    </div>
  );
}

export function HitlTakeover({
  approval,
  pendingCount,
  onResolve,
}: {
  approval: Approval;
  pendingCount: number;
  onResolve: (decisions: ResumeDecision[]) => Promise<void>;
}) {
  const actions = useMemo(() => {
    const list = hitlActionRequests(approval.content);
    return list.length ? list : [{ toolName: undefined, args: approval.content, description: undefined }];
  }, [approval.content]);
  const [index, setIndex] = useState(0);
  const [decisions, setDecisions] = useState<ResumeDecision[]>([]);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setIndex(0);
    setDecisions([]);
    setRejecting(false);
    setReason('');
    setBusy(false);
  }, [approval.id]);

  const action = actions[index];
  const decide = async (decision: ResumeDecision) => {
    const next = [...decisions.slice(0, index), decision];
    setDecisions(next);
    setRejecting(false);
    setReason('');
    if (index < actions.length - 1) {
      setIndex(index + 1);
      return;
    }
    setBusy(true);
    await onResolve(next);
  };

  const description =
    action?.description && !isGenericHitlDescription(action.description) ? action.description : null;

  return (
    <div
      className="rounded-2xl border border-warning/40 bg-surface shadow-card"
      role="region"
      aria-label="Approval needed"
    >
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <span className="approval-pulse grid size-6 place-items-center rounded-md bg-warning/15 text-warning">
          <ShieldAlert className="size-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium">{approvalHeadline(actions)}</div>
          <div className="text-2xs text-muted">
            The agent is paused until you decide
            {pendingCount > 1 ? ` · ${pendingCount} approvals waiting` : ''}
          </div>
        </div>
        {actions.length > 1 && (
          <span className="num text-2xs text-muted">
            {index + 1} / {actions.length}
          </span>
        )}
      </div>
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={index}
          initial={{ opacity: 0, x: 8 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -8 }}
          transition={{ duration: 0.18, ease: 'easeOut' }}
          className="space-y-2.5 px-4 py-3"
        >
          <div className="flex items-baseline gap-2">
            <span className="text-sm font-medium">{humanizeToolName(action?.toolName)}</span>
            {action?.toolName && <span className="font-mono text-2xs text-muted">{action.toolName}</span>}
          </div>
          {description && <p className="text-xs text-muted">{description}</p>}
          <ArgsView args={action?.args} />
          {rejecting && (
            <input
              autoFocus
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              onKeyDown={(e) =>
                e.key === 'Enter' && void decide({ decision: 'reject', reason: reason.trim() || null })
              }
              placeholder="Why not? The agent reads this (optional)"
              aria-label="Reason for rejecting"
              className="h-8 w-full rounded-lg border border-border bg-background px-3 text-sm outline-none focus:border-primary/50"
            />
          )}
        </motion.div>
      </AnimatePresence>
      <div className="flex items-center justify-end gap-2 px-4 pb-3">
        {index > 0 && (
          <Button
            size="sm"
            variant="ghost"
            className="mr-auto"
            onClick={() => setIndex(index - 1)}
            disabled={busy}
          >
            Back
          </Button>
        )}
        {rejecting ? (
          <>
            <Button size="sm" variant="ghost" onClick={() => setRejecting(false)} disabled={busy}>
              Cancel
            </Button>
            <Button
              size="sm"
              variant="danger"
              leftIcon={<X />}
              loading={busy}
              onClick={() => void decide({ decision: 'reject', reason: reason.trim() || null })}
            >
              Reject
            </Button>
          </>
        ) : (
          <>
            <Button
              size="sm"
              variant="secondary"
              leftIcon={<X />}
              onClick={() => setRejecting(true)}
              disabled={busy}
            >
              Reject
            </Button>
            <Button
              size="sm"
              variant="warning"
              leftIcon={<Check />}
              loading={busy}
              onClick={() => void decide({ decision: 'approve' })}
            >
              {index < actions.length - 1 ? 'Approve, next' : 'Approve'}
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
