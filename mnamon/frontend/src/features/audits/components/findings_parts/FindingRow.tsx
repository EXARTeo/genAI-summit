import { ChevronRight, History, MessageSquare } from 'lucide-react';
import { cn } from '@/shared/lib/utils';
import { articleLabel, severityMeta, titleOf, type SealedFinding } from '../../lib/findings';
import { TONE_CLASSES, verdictStyle } from '../../lib/styling';

/** Three small bars: critical/high = 3, medium = 2, low = 1; nothing without a severity. */
export function SeverityMark({ severity, className }: { severity: string | null; className?: string }) {
  const sev = severityMeta(severity);
  if (!sev) return <span className={cn('w-3', className)} aria-hidden />;
  const level = sev.rank <= 1 ? 3 : sev.rank === 2 ? 2 : 1;
  const on =
    sev.rank === 0 ? 'bg-danger' : level === 3 ? 'bg-danger/80' : level === 2 ? 'bg-warning' : 'bg-muted';
  return (
    <span
      className={cn('inline-flex h-3 w-3 shrink-0 items-end gap-px', className)}
      title={`${sev.label} severity`}
      role="img"
      aria-label={`${sev.label} severity`}
    >
      {[1, 2, 3].map((i) => (
        <span
          key={i}
          className={cn('w-[3px] rounded-[1px]', i <= level ? on : 'bg-border')}
          style={{ height: `${i * 33}%` }}
        />
      ))}
    </span>
  );
}

/** One finding as one calm line: verdict colour bar, article, requirement, severity. */
export function FindingRow({
  f,
  selected,
  onSelect,
}: {
  f: SealedFinding;
  selected: boolean;
  onSelect: () => void;
}) {
  const v = verdictStyle(f.verdict);
  const article = articleLabel(f);
  const title = titleOf(f);
  return (
    <button
      type="button"
      data-finding-row={f.id}
      onClick={onSelect}
      aria-expanded={selected}
      title={f.obligation_id}
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
          TONE_CLASSES[v.tone].bg,
        )}
      />
      <span className="sr-only">{v.label}:</span>
      <span className="flex min-w-0 flex-1 flex-col sm:flex-row sm:items-center sm:gap-3">
        <span className="num shrink-0 truncate text-xs font-semibold text-text sm:w-[5.75rem]">
          {article ?? '–'}
        </span>
        <span className={cn('min-w-0 flex-1 truncate text-sm', selected ? 'text-text' : 'text-text/80')}>
          {title ?? f.obligation_id}
        </span>
      </span>
      {f.stale && <History className="size-3.5 shrink-0 text-warning" aria-label="Stale" />}
      {f.annotations.length > 0 && (
        <span className="inline-flex shrink-0 items-center gap-0.5 text-2xs text-muted">
          <MessageSquare className="size-3" />
          <span className="num">{f.annotations.length}</span>
        </span>
      )}
      <SeverityMark severity={f.severity} />
      <ChevronRight
        className={cn(
          'size-3.5 shrink-0 text-muted/60 transition-transform',
          selected && 'rotate-90 text-muted xl:rotate-0 xl:text-text',
        )}
      />
    </button>
  );
}
