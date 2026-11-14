import { Check, Hand, Loader2, X } from 'lucide-react';
import { cn } from '@/shared/lib/utils';
import { Button } from '@/shared/ui';
import type { StageDef, StepState } from '../../lib/pipeline';
import { STEP_HINT, STEP_ICON } from '../../lib/stepMeta';

/** Card height without / with the waiting gate's decision row (px); the graph lays out with these. */
export const STEP_CARD_H = 68;
export const STEP_CARD_ACTION_H = 46;

const STATE_LABEL: Record<StepState, string> = {
  done: 'Done',
  active: 'Running',
  pending: 'Not started',
  blocked: 'Failed',
  'needs-approval': 'Waiting for your decision',
};

/** The status, as an icon chip (never colour alone: the label is there for screen readers). */
function StatusChip({ state }: { state: StepState }) {
  if (state === 'pending') return null;
  const tone = {
    done: 'bg-success/15 text-success',
    active: 'bg-primary/12 text-primary',
    'needs-approval': 'bg-warning/18 text-warning',
    blocked: 'bg-danger/12 text-danger',
  }[state];
  const Icon = { done: Check, active: Loader2, 'needs-approval': Hand, blocked: X }[state];
  return (
    <span
      className={cn('grid size-6 shrink-0 place-items-center rounded-full', tone)}
      title={STATE_LABEL[state]}
    >
      <Icon
        aria-hidden
        className={cn('size-3.5', state === 'active' && 'motion-safe:animate-spin')}
        strokeWidth={state === 'done' || state === 'blocked' ? 3 : 2}
      />
      <span className="sr-only">{STATE_LABEL[state]}</span>
    </span>
  );
}

export interface StepCardProps {
  stage: StageDef;
  state: StepState;
  /** What the step produced; falls back to the step's hint. */
  summary?: string;
  selected?: boolean;
  /** Hover lift and pointer (the graph and the stepper are clickable). */
  interactive?: boolean;
  onReview?: () => void;
  className?: string;
}

/**
 * One pipeline step as a card, in mAgenticX's workflow-node language: icon tile, title, one
 * meaningful subtitle, a status chip; gates in the approval chrome (amber sheen, hand tile,
 * pill radius) with the decision button inside while they wait. Styles: styles/audit-flow.css.
 */
export function StepCard({
  stage,
  state,
  summary,
  selected,
  interactive = true,
  onReview,
  className,
}: StepCardProps) {
  const gate = !!stage.gate;
  const Icon = STEP_ICON[stage.id] ?? Check;
  const waiting = state === 'needs-approval';
  return (
    <div
      className={cn('audit-node h-full w-full', className)}
      data-state={state}
      data-gate={gate ? 'true' : 'false'}
      data-selected={selected ? 'true' : 'false'}
      data-interactive={interactive ? 'true' : 'false'}
    >
      <div className="audit-node-card relative flex h-full flex-col overflow-hidden">
        <span className="audit-node-sheen pointer-events-none absolute inset-x-0 top-0 h-9" aria-hidden />
        {state === 'active' && (
          <span className="audit-node-sweep pointer-events-none absolute inset-0" aria-hidden />
        )}
        <div className="relative flex shrink-0 items-center gap-3 px-3.5" style={{ height: STEP_CARD_H }}>
          <span className="audit-node-tile grid size-9 shrink-0 place-items-center rounded-xl">
            <Icon className="size-[17px]" aria-hidden />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[14px] font-semibold leading-5 tracking-tight text-text">
              {stage.label}
            </span>
            <span
              className={cn(
                'block truncate text-[12.5px] leading-5',
                summary ? 'text-text/70' : 'text-muted',
                waiting && 'font-medium text-warning',
              )}
              title={summary ?? STEP_HINT[stage.id]}
            >
              {waiting ? 'Waiting for your decision' : (summary ?? STEP_HINT[stage.id])}
            </span>
          </span>
          <StatusChip state={state} />
        </div>
        {waiting && onReview && (
          <div
            className="relative flex items-center border-t border-dashed border-warning/40 px-3"
            style={{ height: STEP_CARD_ACTION_H }}
          >
            <Button
              size="sm"
              variant="warning"
              className="nodrag nopan w-full"
              leftIcon={<Hand />}
              onClick={(e) => {
                e.stopPropagation();
                onReview();
              }}
            >
              Review & decide
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
