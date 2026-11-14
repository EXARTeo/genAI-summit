import { motion } from 'framer-motion';
import { Check, Hand, Lock } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { checkDraw } from '@/shared/lib/motion';
import { cn } from '@/shared/lib/utils';
import { Button } from '@/shared/ui';
import { STAGES, formatDuration, stepStates, type StepState } from '../lib/pipeline';
import type { AuditDetail } from '../lib/types';

export interface AuditPipelineProps {
  audit: AuditDetail;
  selected: string;
  onSelect: (stageId: string) => void;
  onReview: () => void;
}

/** Remember which steps just turned done, to flash them once. */
function useJustDone(states: Record<string, StepState>): Set<string> {
  const prev = useRef(states);
  const [flash, setFlash] = useState<Set<string>>(new Set());
  const key = Object.values(states).join(',');
  useEffect(() => {
    const done = Object.keys(states).filter((k) => states[k] === 'done' && prev.current[k] !== 'done');
    prev.current = states;
    if (done.length) setFlash(new Set(done));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  useEffect(() => {
    if (!flash.size) return;
    const t = setTimeout(() => setFlash(new Set()), 1200);
    return () => clearTimeout(t);
  }, [flash]);
  return flash;
}

const STATE_LABEL: Record<StepState, string> = {
  done: 'Done',
  active: 'Running',
  pending: 'Pending',
  blocked: 'Blocked',
  'needs-approval': 'Needs your decision',
};

function Node({ state, gate, flash }: { state: StepState; gate: boolean; flash: boolean }) {
  // Done gates look like any done step: amber is reserved for "needs a human now".
  const base = 'relative z-10 grid size-5 shrink-0 place-items-center rounded-full';
  if (state === 'done') {
    return (
      <span className={cn(base, 'bg-primary/15 text-primary')}>
        {flash ? (
          <svg viewBox="0 0 24 24" className="size-3" fill="none" aria-hidden>
            <motion.path
              d="M5 12.5l4.5 4.5L19 7.5"
              stroke="currentColor"
              strokeWidth={3}
              strokeLinecap="round"
              strokeLinejoin="round"
              variants={checkDraw}
              initial="initial"
              animate="animate"
            />
          </svg>
        ) : (
          <Check className="size-3" strokeWidth={3} />
        )}
      </span>
    );
  }
  if (state === 'active') {
    return (
      <span className={cn(base, 'bg-surface')}>
        <span className="agent-orb absolute inset-0" />
        <span className="size-1.5 rounded-full bg-primary" />
      </span>
    );
  }
  if (state === 'needs-approval') {
    return (
      <span className={cn(base, 'approval-pulse bg-warning text-warning-foreground')}>
        <Hand className="size-3" />
      </span>
    );
  }
  if (state === 'blocked') {
    return (
      <span className={cn(base, 'bg-danger/15 text-danger')}>
        <Lock className="size-3" />
      </span>
    );
  }
  return (
    <span className={cn(base, 'border border-border bg-surface')}>
      {gate ? <Hand className="size-2.5 text-muted" /> : <span className="size-1 rounded-full bg-border" />}
    </span>
  );
}

/** The live pipeline: one compact row per step, the current one expanded. */
export function AuditPipeline({ audit, selected, onSelect, onReview }: AuditPipelineProps) {
  const states = stepStates(audit);
  const flash = useJustDone(states);
  const durations = audit.data.stageDurations ?? {};

  return (
    <ol className="relative">
      {STAGES.map((s, i) => {
        const state = states[s.id];
        const isSel = s.id === selected;
        const isCurrent = state === 'active' || state === 'needs-approval';
        const last = i === STAGES.length - 1;
        const nextDone = !last && states[STAGES[i + 1].id] !== 'pending';
        return (
          <li key={s.id} className="relative">
            {!last && (
              <span
                aria-hidden
                className={cn(
                  'absolute left-[19px] top-[22px] h-[calc(100%-4px)] w-px',
                  state === 'done' && nextDone ? 'bg-primary/40' : 'bg-border',
                )}
              />
            )}
            <button
              type="button"
              onClick={() => onSelect(s.id)}
              aria-current={isSel ? 'step' : undefined}
              aria-label={`${s.label}: ${STATE_LABEL[state]}`}
              className={cn(
                'group relative flex w-full items-start gap-3 rounded-lg px-2.5 py-2 text-left transition-colors duration-150',
                isSel ? 'bg-surface-muted' : 'hover:bg-surface-muted/50',
              )}
            >
              {flash.has(s.id) && (
                <motion.span
                  aria-hidden
                  className="absolute inset-0 rounded-lg bg-primary/10"
                  initial={{ opacity: 1 }}
                  animate={{ opacity: 0 }}
                  transition={{ duration: 1.1, ease: 'easeOut' }}
                />
              )}
              <Node state={state} gate={!!s.gate} flash={flash.has(s.id)} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      'truncate text-sm',
                      state === 'pending' ? 'text-muted' : 'text-text',
                      (isSel || isCurrent) && 'font-medium',
                      state === 'active' && 'text-shimmer',
                      state === 'needs-approval' && 'text-warning',
                    )}
                  >
                    {s.label}
                  </span>
                  {s.gate && state !== 'needs-approval' && (
                    <span className="rounded border border-border px-1 text-[10px] font-medium uppercase tracking-wide text-muted">
                      Gate
                    </span>
                  )}
                  <span className="num ml-auto shrink-0 text-2xs text-muted">
                    {state === 'done' && durations[s.id] != null
                      ? formatDuration(durations[s.id])
                      : state === 'active'
                        ? 'running'
                        : state === 'needs-approval'
                          ? 'waiting'
                          : ''}
                  </span>
                </div>
                {(isCurrent || isSel) && <div className="mt-0.5 text-xs text-muted">{s.description}</div>}
              </div>
            </button>
            {state === 'needs-approval' && (
              <div className="mb-1 ml-[42px] mt-1">
                <Button size="sm" variant="warning" onClick={onReview}>
                  Review & decide
                </Button>
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
