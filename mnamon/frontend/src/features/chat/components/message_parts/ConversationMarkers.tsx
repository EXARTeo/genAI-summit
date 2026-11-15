/**
 * Every marker the conversation draws between (or inside) messages, in one place and one shape,
 * so they read as a family (port of magenticx `message_parts/ConversationMarkers.tsx`):
 *
 *        <headline> ›                           ← opens the task in the agent map
 *   〰〰〰〰〰〰〰〰〰  <label>  〰〰〰〰〰〰〰〰〰
 *
 * - TaskMarker: a background task settled (the wake-up's notice row, and the inline mark of a
 *   result pulled into a busy run).
 * - TaskUpdateMarker: the orchestrator sent a follow-up to a task (`update_async_task`).
 *
 * Written here rather than taken from shadcn: nothing there draws a labelled wavy rule. A new
 * marker goes here, built on MarkerRule, never as a one-off elsewhere. magenticx's compaction
 * marker is not ported: Mnamon has no compaction data to show.
 */
import { motion, useReducedMotion } from 'framer-motion';
import { Check, ChevronRight, CircleAlert, CircleSlash, Send } from 'lucide-react';
import { useId, type ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';
import { taskOutcome, type TaskOutcome } from '../../lib/taskMarkers';

const WAVE_PERIOD = 12;

/** One half of the rule: an SVG wave in the border colour; it drifts while something is in progress. */
function WavyRule({ moving }: { moving: boolean }) {
  const reduceMotion = useReducedMotion();
  // useId's colons are not safe inside url(#…).
  const patternId = `wave${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const animate = moving && !reduceMotion;
  return (
    <div className="relative h-2 min-w-6 flex-1 overflow-hidden text-border" aria-hidden>
      <motion.svg
        className="absolute inset-y-0 left-0 h-2"
        style={{ width: `calc(100% + ${WAVE_PERIOD}px)` }}
        animate={animate ? { x: [0, -WAVE_PERIOD] } : { x: 0 }}
        transition={animate ? { duration: 0.9, ease: 'linear', repeat: Infinity } : { duration: 0 }}
      >
        <defs>
          <pattern id={patternId} width={WAVE_PERIOD} height="8" patternUnits="userSpaceOnUse">
            <path d="M0 4 Q 3 1 6 4 T 12 4" fill="none" stroke="currentColor" strokeWidth="1.25" />
          </pattern>
        </defs>
        <rect width="100%" height="8" fill={`url(#${patternId})`} />
      </motion.svg>
    </div>
  );
}

/** The rule with its label in the middle; a softly pulsing label while in progress. */
function MarkerRule({
  label,
  icon,
  tone = 'text-muted',
  inProgress = false,
}: {
  label: string;
  icon?: ReactNode;
  tone?: string;
  inProgress?: boolean;
}) {
  return (
    <div className="flex items-center gap-3">
      <WavyRule moving={inProgress} />
      <span
        className={cn(
          'flex shrink-0 items-center gap-1 text-xs font-medium',
          tone,
          inProgress && 'motion-safe:animate-pulse',
        )}
      >
        {icon}
        {label}
      </span>
      <WavyRule moving={inProgress} />
    </div>
  );
}

/** The small italic line above the rule; a button when it opens something. */
const HEADLINE =
  'mx-auto flex max-w-full items-center gap-1 rounded-md px-1.5 py-0.5 text-xs italic text-muted transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60';
const HEADLINE_ACTIVE = 'hover:text-text';

function Headline({ text, onOpen }: { text: string; onOpen?: () => void }) {
  if (!onOpen) {
    return (
      <span className={HEADLINE}>
        <span className="min-w-0 truncate">{text}</span>
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`${text}, open the task`}
      className={cn(HEADLINE, HEADLINE_ACTIVE)}
    >
      <span className="min-w-0 truncate">{text}</span>
      <ChevronRight className="size-3.5 shrink-0" aria-hidden />
    </button>
  );
}

/** The rule's label for a task's end, with an icon so it never relies on colour alone. */
function outcomeLabel(outcome: TaskOutcome): { label: string; icon?: ReactNode; tone?: string } {
  if (outcome === 'success') {
    return { label: 'Finished', icon: <Check className="size-3.5" aria-hidden />, tone: 'text-success' };
  }
  if (outcome === 'error') {
    return { label: 'Failed', icon: <CircleAlert className="size-3.5" aria-hidden />, tone: 'text-danger' };
  }
  if (outcome === 'cancelled') {
    return { label: 'Stopped', icon: <CircleSlash className="size-3.5" aria-hidden /> };
  }
  return { label: 'Working…' };
}

export interface TaskMarkerProps {
  /** A task status from any source (`success`, `error`, `cancelled`, `completed`…). */
  status: string;
  /** "General Purpose finished · 22s": the headline above the rule. */
  text: string;
  /** Opens the task in the agent map; without it the headline is plain text. */
  onOpen?: () => void;
  className?: string;
}

/** A background task settled: its name and time above, the outcome on the rule. */
export function TaskMarker({ status, text, onOpen, className }: TaskMarkerProps) {
  const outcome = taskOutcome(status);
  const { label, icon, tone } = outcomeLabel(outcome);
  return (
    <div
      role="separator"
      aria-label={text}
      className={cn('flex w-full flex-col gap-1 py-0.5', className)}
      data-testid="task-marker"
    >
      <Headline text={text} onOpen={onOpen} />
      <MarkerRule label={label} icon={icon} tone={tone} inProgress={outcome === 'running'} />
    </div>
  );
}

export interface TaskUpdateMarkerProps {
  /** "Sent an update to General Purpose". */
  text: string;
  /** What the orchestrator sent, clipped to two lines. */
  detail?: string;
  onOpen?: () => void;
  className?: string;
}

/** The orchestrator followed up on a background task: the headline, what it sent, then the rule. */
export function TaskUpdateMarker({ text, detail, onOpen, className }: TaskUpdateMarkerProps) {
  return (
    <div
      role="separator"
      aria-label={text}
      className={cn('flex w-full flex-col gap-1 py-0.5', className)}
      data-testid="task-update-marker"
    >
      <Headline text={text} onOpen={onOpen} />
      {detail ? (
        <p
          className="mx-auto line-clamp-2 max-w-xl px-2 text-center text-xs text-muted/90 [overflow-wrap:anywhere]"
          title={detail}
        >
          {detail}
        </p>
      ) : null}
      <MarkerRule label="Update sent" icon={<Send className="size-3.5" aria-hidden />} />
    </div>
  );
}
