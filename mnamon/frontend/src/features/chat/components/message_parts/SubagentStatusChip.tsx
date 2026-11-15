/**
 * A sub-agent's status chip (magenticx `message_parts/subagentStatus.tsx`): teal while working,
 * amber when it needs a human, green when done. Shared by the inline card and the agent map.
 * `compact` drops the word on a phone (under 420 px), keeping the icon.
 */
import { Check, CircleAlert, CircleDashed, CircleSlash, Clock, Loader2 } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';
import type { SubagentStatus } from '../../lib/timeline';

const STATUS_META: Record<SubagentStatus, { label: string; chip: string; icon: ReactNode }> = {
  pending: {
    label: 'Starting',
    chip: 'bg-surface-sunken text-muted',
    icon: <CircleDashed className="size-3" aria-hidden />,
  },
  running: {
    label: 'Running',
    chip: 'bg-primary/10 text-primary',
    icon: <Loader2 className="size-3 motion-safe:animate-spin" aria-hidden />,
  },
  awaiting_approval: {
    label: 'Awaiting approval',
    chip: 'bg-warning/15 text-warning',
    icon: <Clock className="size-3" aria-hidden />,
  },
  done: { label: 'Done', chip: 'bg-success/15 text-success', icon: <Check className="size-3" aria-hidden /> },
  failed: {
    label: 'Failed',
    chip: 'bg-danger/10 text-danger',
    icon: <CircleAlert className="size-3" aria-hidden />,
  },
  cancelled: {
    label: 'Cancelled',
    chip: 'bg-surface-sunken text-muted',
    icon: <CircleSlash className="size-3" aria-hidden />,
  },
};

export function SubagentStatusChip({
  status,
  compact = false,
  className,
}: {
  status: SubagentStatus;
  compact?: boolean;
  className?: string;
}) {
  const meta = STATUS_META[status];
  return (
    <span
      title={meta.label}
      className={cn(
        'flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-2xs font-medium',
        compact && 'max-[419px]:gap-0 max-[419px]:px-1.5 max-[419px]:py-1',
        meta.chip,
        className,
      )}
    >
      {meta.icon}
      <span className={cn(compact && 'max-[419px]:sr-only')}>{meta.label}</span>
    </span>
  );
}
