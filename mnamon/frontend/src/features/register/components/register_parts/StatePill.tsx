import { cn } from '@/shared/lib/utils';
import { Tooltip } from '@/shared/ui';
import { TONE_CLASSES } from '@/features/audits/lib/styling';
import { stateMeta } from '../../lib/register';
import type { RegisterItem } from '../../lib/types';

/** The item's state now: Open, Needs review, Accepted risk, Resolved, Monitoring. */
export function StatePill({
  item,
  className,
}: {
  item: Pick<RegisterItem, 'state' | 'verdict'>;
  className?: string;
}) {
  const meta = stateMeta(item);
  return (
    <Tooltip content={meta.description}>
      <span
        className={cn(
          'inline-flex h-5 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-2 text-2xs font-medium',
          TONE_CLASSES[meta.tone].pill,
          className,
        )}
      >
        <span className={cn('size-1.5 rounded-full', TONE_CLASSES[meta.tone].dot)} />
        {meta.label}
      </span>
    </Tooltip>
  );
}
