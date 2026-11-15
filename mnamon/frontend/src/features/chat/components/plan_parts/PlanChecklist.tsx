// Port of magenticx `plan/PlanChecklist.tsx` (rail styles in styles/agent-map.css).
import * as React from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { Check } from 'lucide-react';

import { cn } from '@/shared/lib/utils';
import {
  formatStepDuration,
  planStepLabel,
  type PlanStep,
  type PlanStepState,
} from '../../lib/conversationPlans';

// One plan as a checklist on a connector rail (styles/plan.css): a marker per
// step on the rail, the step beside it. Done: a filled check in the brand
// colour, the text muted, the rail behind it filled. Now: the row tinted, with
// the working hairline along its top edge (`glow-border`).
// Not started: a hollow circle, faint. Left in progress by an answer that has
// ended: a dashed circle. Steps keep the plan's order — a status change
// animates in place, a new step slides in.

const EASE = [0.22, 1, 0.36, 1] as const;

function Marker({ state }: { state: PlanStepState }) {
  const reduceMotion = useReducedMotion();
  return (
    <span className="plan-step-marker" aria-hidden>
      <AnimatePresence initial={false} mode="popLayout">
        {state === 'done' ? (
          <motion.span
            key="done"
            initial={reduceMotion ? { opacity: 0 } : { scale: 0.4, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ opacity: 0, transition: { duration: 0.12 } }}
            transition={{ type: 'spring', stiffness: 520, damping: 26 }}
            className="absolute inset-0 flex items-center justify-center rounded-full bg-primary text-primary-foreground"
          >
            <Check className="h-3 w-3" strokeWidth={3.25} />
          </motion.span>
        ) : state === 'active' ? (
          <motion.span
            key="active"
            initial={reduceMotion ? { opacity: 0 } : { scale: 0.6, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ opacity: 0, transition: { duration: 0.12 } }}
            transition={{ duration: 0.3, ease: EASE }}
            className="absolute inset-0 flex items-center justify-center rounded-full border-2 border-primary bg-surface"
          >
            <span className="size-2 rounded-full bg-primary" />
          </motion.span>
        ) : (
          <motion.span
            key={state}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, transition: { duration: 0.12 } }}
            transition={{ duration: 0.24 }}
            className={cn(
              'absolute inset-0 rounded-full bg-surface',
              state === 'stopped'
                ? 'border-[1.5px] border-dashed border-primary/45'
                : 'border-[1.5px] border-muted/30',
            )}
          />
        )}
      </AnimatePresence>
    </span>
  );
}

function StepTime({ step }: { step: PlanStep }) {
  if (step.state === 'active') {
    return (
      <span className="flex shrink-0 items-center gap-1.5 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
        <span className="relative flex h-1.5 w-1.5">
          <span className="absolute inline-flex h-full w-full rounded-full bg-current opacity-70 motion-safe:animate-ping" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
        </span>
        now
      </span>
    );
  }
  if (step.state === 'stopped') {
    return <span className="shrink-0 text-[11px] leading-5 text-muted">Not finished</span>;
  }
  const took = step.state === 'done' ? formatStepDuration(step.durationMs) : null;
  return took ? <span className="shrink-0 text-xs tabular-nums leading-5 text-muted">{took}</span> : null;
}

type PlanChecklistProps = {
  steps: PlanStep[];
  /** Names the list ("Plan for question 3"). */
  label: string;
  className?: string;
};

export function PlanChecklist({ steps, label, className }: PlanChecklistProps) {
  const reduceMotion = useReducedMotion();
  // The rows cascade in when the list first shows; a step that arrives later
  // (the agent extends its plan) slides in on its own.
  const [firstPaint, setFirstPaint] = React.useState(true);
  React.useEffect(() => setFirstPaint(false), []);

  return (
    <ol aria-label={label} className={cn('plan-steps', className)}>
      <AnimatePresence initial>
        {steps.map((step, index) => {
          const active = step.state === 'active';
          return (
            <motion.li
              key={step.key}
              aria-label={planStepLabel(step, index, steps.length)}
              aria-current={active ? 'step' : undefined}
              data-state={step.state}
              className="plan-step"
              initial={reduceMotion ? { opacity: 0 } : { opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, transition: { duration: 0.15 } }}
              transition={{
                duration: 0.32,
                ease: EASE,
                delay: firstPaint && !reduceMotion ? 0.04 + Math.min(index, 12) * 0.035 : 0,
              }}
            >
              <Marker state={step.state} />
              <div className="rounded-xl">
                <div
                  className={cn(
                    'relative flex items-start gap-3 overflow-hidden rounded-xl px-3 py-2.5',
                    active && 'glow-border',
                  )}
                >
                  {/* The tint, fading in and out as the step starts and ends. */}
                  <span
                    aria-hidden
                    className={cn(
                      'pointer-events-none absolute inset-0 rounded-xl bg-primary/5 transition-opacity duration-500 ease-out',
                      active ? 'opacity-100' : 'opacity-0',
                    )}
                  />
                  <p
                    className={cn(
                      'relative min-w-0 flex-1 text-[13.5px] leading-5 transition-colors duration-500 ease-out',
                      step.state === 'done'
                        ? 'text-muted'
                        : step.state === 'pending'
                          ? 'text-text/70'
                          : active
                            ? 'font-medium text-text'
                            : 'text-text/85',
                    )}
                  >
                    {step.content}
                  </p>
                  <span className="relative flex shrink-0">
                    <StepTime step={step} />
                  </span>
                </div>
              </div>
            </motion.li>
          );
        })}
      </AnimatePresence>
    </ol>
  );
}
