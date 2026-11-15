import { ChevronRight } from 'lucide-react';
import { formatStarted } from '@/shared/lib/labels';
import { cn } from '@/shared/lib/utils';
import { VerdictPill } from '@/features/audits/components/artifact_parts/common';
import { SeverityMark } from '@/features/audits/components/findings_parts/FindingRow';
import { TONE_CLASSES } from '@/features/audits/lib/styling';
import { itemArticle, stateMeta } from '../../lib/register';
import type { RegisterItem } from '../../lib/types';
import { StatePill } from './StatePill';

/** One register item: state bar, article, title; then state, verdict and since when. */
export function RegisterRow({
  item,
  selected,
  onSelect,
}: {
  item: RegisterItem;
  selected: boolean;
  onSelect: () => void;
}) {
  const meta = stateMeta(item);
  const since = item.opened_at ?? item.history[0]?.at ?? item.created_at;
  return (
    <button
      type="button"
      data-register-row={item.obligation_id}
      onClick={onSelect}
      aria-expanded={selected}
      title={item.obligation_id}
      className={cn(
        'group relative flex w-full items-center gap-3 py-2.5 pl-4 pr-3 text-left transition-colors',
        'focus-visible:bg-hover focus-visible:outline-none',
        selected ? 'bg-hover-strong' : 'hover:bg-hover',
      )}
    >
      <span
        aria-hidden
        className={cn(
          'absolute inset-y-1.5 left-1 rounded-full transition-[width]',
          selected ? 'w-1' : 'w-[3px]',
          TONE_CLASSES[meta.tone].bg,
        )}
      />
      <span className="flex min-w-0 flex-1 flex-col gap-1.5">
        <span className="flex min-w-0 items-baseline gap-3">
          <span className="num w-[5.75rem] shrink-0 truncate text-xs font-semibold text-text">
            {itemArticle(item)}
          </span>
          <span className={cn('min-w-0 flex-1 truncate text-sm', selected ? 'text-text' : 'text-text/80')}>
            {item.title ?? item.obligation_id}
          </span>
        </span>
        <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-2xs text-muted">
          <StatePill item={item} />
          <VerdictPill verdict={item.verdict} />
          <span className="num truncate">
            {item.state === 'open' ? 'open since' : 'tracked since'} {formatStarted(since) || '–'}
          </span>
        </span>
      </span>
      <SeverityMark severity={item.severity} />
      <ChevronRight
        className={cn(
          'size-3.5 shrink-0 text-muted/60 transition-transform',
          selected && 'rotate-90 text-muted xl:rotate-0 xl:text-text',
        )}
      />
    </button>
  );
}
