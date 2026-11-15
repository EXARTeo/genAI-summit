// Written from scratch: a compact verdict summary (stacked bar + counts) for one audit row;
// no prebuilt component shows a proportional verdict mix this small.
import { cn } from '@/shared/lib/utils';
import { Tooltip } from '@/shared/ui';
import type { VerdictBucket } from '../../lib/auditList';
import { TONE_CLASSES } from '../../lib/styling';

export function FindingsSummary({ buckets }: { buckets: VerdictBucket[] | null }) {
  if (!buckets) return <span className="text-xs text-muted">—</span>;
  const total = buckets.reduce((s, b) => s + b.count, 0);
  const gaps = buckets.find((b) => b.id === 'gap')?.count ?? 0;

  return (
    <Tooltip
      content={
        <ul className="space-y-0.5">
          {buckets.map((b) => (
            <li key={b.id} className="flex items-center gap-2">
              <span className={cn('size-2 rounded-full', TONE_CLASSES[b.tone].dot)} />
              <span className="num w-5 text-right">{b.count}</span>
              <span>{b.label}</span>
            </li>
          ))}
        </ul>
      }
    >
      <div className="min-w-0 space-y-1.5">
        <div className="flex h-1.5 overflow-hidden rounded-full bg-surface-muted">
          {buckets
            .filter((b) => b.count > 0)
            .map((b) => (
              <span
                key={b.id}
                className={cn('h-full', b.id === 'na' ? 'bg-muted/40' : TONE_CLASSES[b.tone].bg)}
                style={{ width: `${(b.count / total) * 100}%` }}
              />
            ))}
        </div>
        <div className="num flex items-center gap-x-2 overflow-hidden whitespace-nowrap text-xs">
          <span className={cn('font-semibold', gaps > 0 ? 'text-danger' : 'text-success')}>
            {gaps > 0 ? `${gaps} ${gaps === 1 ? 'gap' : 'gaps'}` : 'No gaps'}
          </span>
          {buckets
            // "n/a" is the bar's grey part and in the tooltip; as text it overflowed narrow rows.
            .filter((b) => b.id !== 'gap' && b.id !== 'na' && b.count > 0)
            .map((b) => (
              <span key={b.id} className="flex items-center gap-1 text-muted">
                <span className={cn('size-1.5 rounded-full', TONE_CLASSES[b.tone].dot)} />
                {b.count} {b.short}
              </span>
            ))}
        </div>
      </div>
    </Tooltip>
  );
}
