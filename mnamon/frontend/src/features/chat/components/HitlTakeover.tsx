/**
 * The approval takeover (magenticx `HitlInputTakeover.tsx`): while the run is paused on an
 * approval it replaces the composer, in the composer's own card. Compact: a shield tile,
 * "Approval required" and what the tool does (a chevron opens its arguments), then one row with
 * an optional reason, Reject and Approve. Approve is amber (`warning`: needs a human), not
 * magenticx's green, which this app keeps for verdicts.
 *
 * A batched interrupt (the agent gated several tool calls at once) is a deck: one pill per action,
 * decide each (a first decision moves on, a revisit overwrites), then "Send decisions" sends them
 * together (LangChain resolves the batch atomically). Each rejection carries its own reason.
 */
import { AnimatePresence, motion, useReducedMotion, type Variants } from 'framer-motion';
import { Check, ChevronDown, Loader2, ShieldAlert, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { cn } from '@/shared/lib/utils';
import { Button } from '@/shared/ui';
import { formatArgs, hitlActionRequests, humanizeToolName, isGenericHitlDescription } from '../lib/hitl';
import type { HitlActionRequest } from '../lib/hitl';
import type { Approval } from '../lib/timeline';
import type { ResumeDecision } from '../lib/types';

type Decision = 'approve' | 'reject';

const describe = (a: HitlActionRequest | undefined) =>
  a?.description && !isGenericHitlDescription(a.description) ? a.description : null;

/** What is being approved: the tool, then its simple arguments, then all of them on demand. */
function ActionDetail({ action }: { action: HitlActionRequest }) {
  const [open, setOpen] = useState(false);
  const args = action.args;
  const entries =
    args && typeof args === 'object' && !Array.isArray(args)
      ? Object.entries(args as Record<string, unknown>)
      : [];
  const simple = entries.filter(([, v]) => typeof v !== 'object' || v === null).slice(0, 6);
  const description = describe(action);
  return (
    <div className="space-y-2">
      <div className="flex items-baseline gap-2">
        <span className="text-sm font-medium">{humanizeToolName(action.toolName)}</span>
        {action.toolName && <span className="font-mono text-2xs text-muted">{action.toolName}</span>}
      </div>
      {description && <p className="text-xs text-muted">{description}</p>}
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
        <>
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="flex items-center gap-1 text-2xs text-muted hover:text-text"
          >
            <ChevronDown className={cn('size-3 transition-transform', open && 'rotate-180')} />
            {open ? 'Hide' : 'Show'} full arguments
          </button>
          {open && (
            <pre className="max-h-40 overflow-auto rounded-lg bg-surface-muted p-2 font-mono text-2xs leading-relaxed">
              {formatArgs(args)}
            </pre>
          )}
        </>
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
  const reduce = useReducedMotion();
  const actions = useMemo<HitlActionRequest[]>(() => {
    const list = hitlActionRequests(approval.content);
    return list.length ? list : [{ toolName: undefined, args: approval.content, description: undefined }];
  }, [approval.content]);
  const total = actions.length;
  const isBatch = total > 1;

  const [busy, setBusy] = useState<Decision | 'submit' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const [decisions, setDecisions] = useState<(Decision | null)[]>(() => actions.map(() => null));
  const [reasons, setReasons] = useState<string[]>(() => actions.map(() => ''));
  const [exit, setExit] = useState<Decision | 'next' | 'prev'>('next');
  const reasonRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setBusy(null);
    setError(null);
    setDetailOpen(false);
    setIndex(0);
    setDecisions(actions.map(() => null));
    setReasons(actions.map(() => ''));
    reasonRef.current?.focus({ preventScroll: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [approval.id]);

  const submit = async (resolved: ResumeDecision[], kind: Decision | 'submit') => {
    setBusy(kind);
    setError(null);
    try {
      await onResolve(resolved);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The decision was not sent. Try again.');
      setBusy(null);
    }
  };

  const reasonOf = (i: number) => reasons[i]?.trim() || null;
  const single = (decision: Decision) =>
    void submit([decision === 'reject' ? { decision, reason: reasonOf(0) } : { decision }], decision);

  const decideCard = (decision: Decision) => {
    if (busy) return;
    const first = decisions[index] === null;
    setDecisions((list) => list.map((d, i) => (i === index ? decision : d)));
    if (first && index < total - 1) {
      setExit(decision);
      setIndex(index + 1);
    }
  };
  const goTo = (target: number) => {
    if (busy || target === index || target < 0 || target >= total) return;
    setExit(target > index ? 'next' : 'prev');
    setIndex(target);
  };
  const decide = (decision: Decision) => (isBatch ? decideCard(decision) : single(decision));

  const allDecided = decisions.every((d) => d !== null);
  const rejected = decisions.filter((d) => d === 'reject').length;
  const sendAll = () =>
    void submit(
      decisions.map((d, i) =>
        d === 'reject' ? { decision: 'reject', reason: reasonOf(i) } : { decision: 'approve' },
      ),
      'submit',
    );

  const current = actions[index];
  const currentDecision = decisions[index];
  const subtitle = describe(current) ?? humanizeToolName(current?.toolName);

  const slide = { approve: 40, reject: -40, next: -32, prev: 32 } as const;
  const variants: Variants = {
    enter: (k: keyof typeof slide) => (reduce ? { opacity: 0 } : { opacity: 0, x: -slide[k] }),
    center: { opacity: 1, x: 0 },
    exit: (k: keyof typeof slide) =>
      reduce
        ? { opacity: 0, transition: { duration: 0.1 } }
        : { opacity: 0, x: slide[k], transition: { duration: 0.16, ease: 'easeIn' } },
  };

  return (
    <section
      className="overflow-hidden rounded-[1.75rem] border border-border bg-surface shadow-card"
      aria-label="Approval required"
      aria-busy={busy !== null}
    >
      <div className="flex items-center gap-3 px-4 pt-4 sm:px-5">
        <span className="approval-pulse grid size-9 shrink-0 place-items-center rounded-xl bg-warning/15 text-warning ring-1 ring-warning/25">
          <ShieldAlert className="size-[18px]" />
        </span>
        {isBatch ? (
          <>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold">Approve {total} actions</span>
              <span className="block truncate text-xs text-muted">
                {humanizeToolName(current?.toolName)} · {index + 1} of {total}
              </span>
            </span>
            <div role="tablist" aria-label="Actions" className="flex shrink-0 items-center gap-1">
              {actions.map((a, i) => {
                const d = decisions[i];
                return (
                  <button
                    key={i}
                    type="button"
                    role="tab"
                    aria-selected={i === index}
                    aria-label={`Action ${i + 1}: ${humanizeToolName(a.toolName)}${d ? ` (${d === 'approve' ? 'approved' : 'rejected'})` : ''}`}
                    onClick={() => goTo(i)}
                    disabled={busy !== null}
                    className={cn(
                      'num grid size-7 place-items-center rounded-full text-2xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60',
                      d === 'approve'
                        ? 'bg-warning/15 text-warning'
                        : d === 'reject'
                          ? 'bg-danger/15 text-danger'
                          : 'bg-surface-muted text-muted hover:text-text',
                      i === index && 'ring-2 ring-primary/40 ring-offset-1 ring-offset-surface',
                    )}
                  >
                    {d === 'approve' ? (
                      <Check className="size-3.5" />
                    ) : d === 'reject' ? (
                      <X className="size-3.5" />
                    ) : (
                      i + 1
                    )}
                  </button>
                );
              })}
            </div>
          </>
        ) : (
          <button
            type="button"
            onClick={() => setDetailOpen((o) => !o)}
            aria-expanded={detailOpen}
            aria-label={detailOpen ? 'Hide approval details' : 'Show approval details'}
            className="group flex min-w-0 flex-1 items-center gap-2 rounded-lg text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-warning/50"
          >
            <span className="min-w-0">
              <span className="flex items-center gap-2 text-sm font-semibold">
                Approval required
                {pendingCount > 1 && (
                  <span className="rounded-full bg-warning/15 px-2 py-0.5 text-2xs font-medium text-warning">
                    1 of {pendingCount}
                  </span>
                )}
              </span>
              <span className="block truncate text-xs text-muted">{subtitle}</span>
            </span>
            <ChevronDown
              className={cn(
                'size-4 shrink-0 text-muted transition-transform group-hover:text-text',
                detailOpen && 'rotate-180',
              )}
            />
          </button>
        )}
      </div>

      {!isBatch && detailOpen && current && (
        <div className="mx-4 mt-3 max-h-[min(22rem,45vh)] overflow-y-auto rounded-2xl border border-border bg-surface-muted/50 px-3.5 py-3 sm:mx-5">
          <ActionDetail action={current} />
        </div>
      )}

      {isBatch && (
        <div className="relative mx-4 mt-3 overflow-hidden sm:mx-5">
          <AnimatePresence mode="popLayout" custom={exit} initial={false}>
            {busy === 'submit' ? (
              <motion.div
                key="submitting"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex h-24 items-center justify-center gap-2 text-sm text-muted"
              >
                <Loader2 className="size-4 animate-spin" /> Resuming with your decisions…
              </motion.div>
            ) : (
              <motion.div
                key={index}
                custom={exit}
                variants={variants}
                initial="enter"
                animate="center"
                exit="exit"
                transition={{ duration: reduce ? 0.12 : 0.2, ease: 'easeOut' }}
                className="max-h-[min(18rem,40vh)] overflow-y-auto rounded-2xl border border-border bg-surface-muted/50 px-3.5 py-3"
              >
                {current && <ActionDetail action={current} />}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}

      {error && (
        <p role="alert" className="px-4 pt-2 text-xs text-danger sm:px-5">
          {error}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 px-4 pb-4 pt-3 sm:flex-nowrap sm:px-5">
        <input
          ref={reasonRef}
          value={reasons[index] ?? ''}
          onChange={(e) => setReasons((list) => list.map((r, i) => (i === index ? e.target.value : r)))}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && busy === null) {
              e.preventDefault();
              decide('approve');
            }
          }}
          placeholder={isBatch ? 'Reason if you reject (optional)' : 'Reason (optional)'}
          aria-label={isBatch ? `Rejection reason for action ${index + 1}` : 'Reason (optional)'}
          disabled={busy !== null}
          className="h-10 w-full min-w-0 rounded-full border border-border bg-surface-muted/60 px-4 text-sm outline-none transition-colors placeholder:text-muted focus-visible:border-primary/40 focus-visible:bg-background focus-visible:ring-2 focus-visible:ring-primary/15 disabled:opacity-60 sm:w-auto sm:flex-1"
        />
        <Button
          variant="outline"
          aria-pressed={isBatch ? currentDecision === 'reject' : undefined}
          onClick={() => decide('reject')}
          disabled={busy !== null}
          leftIcon={busy === 'reject' ? <Loader2 className="animate-spin" /> : <X />}
          className={cn(
            'h-10 flex-1 rounded-full px-4 sm:flex-none',
            isBatch && currentDecision === 'reject'
              ? 'border-transparent bg-danger text-danger-foreground hover:bg-danger/90'
              : 'text-muted hover:border-danger/40 hover:bg-danger/10 hover:text-danger',
          )}
        >
          Reject
        </Button>
        <Button
          variant="warning"
          aria-pressed={isBatch ? currentDecision === 'approve' : undefined}
          onClick={() => decide('approve')}
          disabled={busy !== null}
          leftIcon={busy === 'approve' ? <Loader2 className="animate-spin" /> : <Check />}
          className={cn(
            'h-10 flex-1 rounded-full px-4 sm:flex-none',
            isBatch && currentDecision === 'reject' && 'border border-border bg-transparent text-muted',
          )}
        >
          Approve
        </Button>
      </div>

      {isBatch && allDecided && busy !== 'submit' && (
        <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-3 sm:px-5">
          <span className="text-xs text-muted">
            {total - rejected} approved{rejected ? ` · ${rejected} rejected` : ''}
          </span>
          <Button
            onClick={sendAll}
            disabled={busy !== null}
            leftIcon={<Check />}
            className="h-9 rounded-full px-4"
          >
            Send decisions
          </Button>
        </div>
      )}
    </section>
  );
}
