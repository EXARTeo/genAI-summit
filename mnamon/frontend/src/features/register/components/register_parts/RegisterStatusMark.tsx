import { cn } from '@/shared/lib/utils';
import { Tooltip } from '@/shared/ui';
import { TONE_CLASSES } from '@/features/audits/lib/styling';
import { statusMeta } from '../../lib/register';

/** A small, calm marker of what this audit meant for the register: New, Still open, Fixed, ... */
export function RegisterStatusMark({
  status,
  className,
}: {
  status: string | null | undefined;
  className?: string;
}) {
  const meta = statusMeta(status);
  if (!meta || status === 'unchanged') return null;
  return (
    <Tooltip content={meta.description}>
      <span
        className={cn(
          'inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-md bg-surface-muted/70 px-1.5 text-2xs font-medium',
          TONE_CLASSES[meta.tone].text,
          className,
        )}
      >
        <span className={cn('size-1.5 rounded-full', TONE_CLASSES[meta.tone].dot)} />
        {meta.label}
      </span>
    </Tooltip>
  );
}
