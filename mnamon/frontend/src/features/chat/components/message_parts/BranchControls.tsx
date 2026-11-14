/**
 * The branch switcher of a message (magenticx `message_parts/BranchControls.tsx`): ‹ 2/3 ›
 * between the versions an edit or a retry created. Nothing when there is only one.
 */
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { cn } from '@/shared/lib/utils';
import { IconButton } from '@/shared/ui';

const ARROW = 'size-6 text-muted hover:bg-hover hover:text-text active:bg-hover-strong [&_svg]:size-3.5';

export function BranchControls({
  index,
  count,
  onSelect,
  className,
}: {
  index: number;
  count: number;
  onSelect: (index: number) => void;
  className?: string;
}) {
  if (count < 2) return null;
  const current = Math.min(Math.max(index, 0), count - 1);
  return (
    <div
      role="group"
      aria-label="Versions"
      className={cn('inline-flex items-center gap-1 text-[11px] font-medium text-muted/80', className)}
    >
      <IconButton
        label="Previous version"
        icon={<ChevronLeft />}
        className={ARROW}
        disabled={current === 0}
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => onSelect(current - 1)}
      />
      <span className="num min-w-[1.75rem] text-center" aria-live="polite">
        {current + 1}/{count}
      </span>
      <IconButton
        label="Next version"
        icon={<ChevronRight />}
        className={ARROW}
        disabled={current >= count - 1}
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => onSelect(current + 1)}
      />
    </div>
  );
}
