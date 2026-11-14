import { motion } from 'framer-motion';
import { Hand, Lock } from 'lucide-react';
import type { ReactNode } from 'react';
import { checkDraw } from '@/shared/lib/motion';
import { cn } from '@/shared/lib/utils';

export type StepState = 'done' | 'active' | 'pending' | 'blocked' | 'needs-approval';

export interface StepItem {
  id: string;
  title: ReactNode;
  description?: ReactNode;
  state: StepState;
  /** Right-aligned meta (duration, cost, timestamp). */
  meta?: ReactNode;
  /** Extra content under an item (vertical only), e.g. an approval card. */
  content?: ReactNode;
}

export interface StepperProps {
  steps: StepItem[];
  orientation?: 'vertical' | 'horizontal';
  onStepClick?: (id: string) => void;
  className?: string;
}

const STATE_LABEL: Record<StepState, string> = {
  done: 'Done',
  active: 'Running',
  pending: 'Pending',
  blocked: 'Blocked',
  'needs-approval': 'Needs approval',
};

function Indicator({ state, index }: { state: StepState; index: number }) {
  const base = 'relative grid size-8 shrink-0 place-items-center rounded-full border-2 text-xs font-semibold';
  switch (state) {
    case 'done':
      return (
        <span className={cn(base, 'border-success bg-success text-white')}>
          <svg viewBox="0 0 24 24" className="size-4" fill="none" aria-hidden>
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
        </span>
      );
    case 'active':
      return (
        <span className={cn(base, 'border-primary bg-primary/10 text-primary')}>
          <span className="agent-orb absolute inset-1 rounded-full opacity-80" />
          <span className="absolute -inset-1 animate-ping rounded-full border border-primary/40" />
        </span>
      );
    case 'needs-approval':
      return (
        <span className={cn(base, 'approval-pulse border-warning bg-warning/15 text-warning')}>
          <Hand className="size-4" />
        </span>
      );
    case 'blocked':
      return (
        <span className={cn(base, 'border-danger/60 bg-danger/10 text-danger')}>
          <Lock className="size-3.5" />
        </span>
      );
    default:
      return <span className={cn(base, 'border-border bg-surface text-muted')}>{index + 1}</span>;
  }
}

/** Pipeline progress. States: done / active / pending / blocked / needs-approval. */
export function Stepper({ steps, orientation = 'vertical', onStepClick, className }: StepperProps) {
  if (orientation === 'horizontal') {
    return (
      <ol className={cn('flex w-full items-start', className)}>
        {steps.map((s, i) => (
          <li key={s.id} className="relative flex flex-1 flex-col items-center text-center">
            {i > 0 && (
              <span
                aria-hidden
                className={cn(
                  'absolute right-1/2 top-4 h-0.5 w-full -translate-y-1/2',
                  steps[i - 1].state === 'done' ? 'bg-success' : 'bg-border',
                )}
              />
            )}
            <button
              type="button"
              disabled={!onStepClick}
              onClick={() => onStepClick?.(s.id)}
              className="relative z-10 flex flex-col items-center gap-2 rounded-lg px-1 disabled:cursor-default"
              aria-label={`${typeof s.title === 'string' ? s.title : `Step ${i + 1}`}: ${STATE_LABEL[s.state]}`}
            >
              <Indicator state={s.state} index={i} />
              <span
                className={cn(
                  'max-w-[9rem] text-xs font-medium',
                  s.state === 'active' ? 'text-shimmer' : s.state === 'pending' ? 'text-muted' : 'text-text',
                )}
              >
                {s.title}
              </span>
            </button>
          </li>
        ))}
      </ol>
    );
  }

  return (
    <ol className={cn('relative', className)}>
      {steps.map((s, i) => {
        const last = i === steps.length - 1;
        return (
          <li key={s.id} className="relative flex gap-4 pb-6 last:pb-0">
            {!last && (
              <span
                aria-hidden
                className={cn(
                  'absolute left-4 top-9 -ml-px h-[calc(100%-2.5rem)] w-0.5 rounded-full',
                  s.state === 'done' ? 'bg-success/70' : 'bg-border',
                )}
              />
            )}
            <Indicator state={s.state} index={i} />
            <div className="min-w-0 flex-1 pt-1">
              <button
                type="button"
                disabled={!onStepClick}
                onClick={() => onStepClick?.(s.id)}
                className="flex w-full items-start justify-between gap-3 text-left disabled:cursor-default"
              >
                <div className="min-w-0">
                  <div
                    className={cn(
                      'text-sm font-medium',
                      s.state === 'active' && 'text-shimmer',
                      s.state === 'pending' && 'text-muted',
                    )}
                  >
                    {s.title}
                  </div>
                  {s.description && <div className="mt-0.5 text-sm text-muted">{s.description}</div>}
                </div>
                <div className="flex shrink-0 items-center gap-2 text-xs text-muted">
                  {s.meta}
                  <span className="sr-only">{STATE_LABEL[s.state]}</span>
                </div>
              </button>
              {s.content && <div className="mt-3">{s.content}</div>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
