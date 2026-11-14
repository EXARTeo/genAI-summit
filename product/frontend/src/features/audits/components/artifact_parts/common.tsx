import { BookMarked, Brain, ExternalLink, Scale } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { cn } from '@/shared/lib/utils';
import { Badge, Tooltip } from '@/shared/ui';
import { traceUrl } from '../../lib/langfuse';
import { TONE_CLASSES, confidenceLabel, verdictStyle, type Tone } from '../../lib/styling';
import type { Citation } from '../../lib/types';

export function VerdictPill({ verdict, className }: { verdict: string; className?: string }) {
  const v = verdictStyle(verdict);
  return (
    <Tooltip content={v.description}>
      <span
        className={cn(
          'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold',
          TONE_CLASSES[v.tone].pill,
          className,
        )}
      >
        <span className={cn('size-1.5 rounded-full', TONE_CLASSES[v.tone].dot)} />
        {v.label}
      </span>
    </Tooltip>
  );
}

export function ConfidenceBar({ value }: { value: number }) {
  const tone: Tone = value >= 0.8 ? 'success' : value >= 0.55 ? 'warning' : 'danger';
  return (
    <div className="flex items-center gap-2 text-xs text-muted">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-surface-muted">
        <div
          className={cn('h-full rounded-full transition-[width] duration-700', TONE_CLASSES[tone].bg)}
          style={{ width: `${Math.round(value * 100)}%` }}
        />
      </div>
      <span>
        {Math.round(value * 100)}% · {confidenceLabel(value)}
      </span>
    </div>
  );
}

/** "applied MEM-0042" chip linking to the memory ledger. */
export function MemoryChip({ id, prefix = 'applied' }: { id: string; prefix?: string }) {
  return (
    <Link to={`/memory?entry=${encodeURIComponent(id)}`} className="inline-flex">
      <Badge tone="info" icon={<Brain />} className="hover:border-info/60">
        {prefix} {id}
      </Badge>
    </Link>
  );
}

export function MemoryChips({ ids }: { ids?: string[] }) {
  if (!ids?.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {ids.map((m) => (
        <MemoryChip key={m} id={m} />
      ))}
    </div>
  );
}

export function CitationChip({ c }: { c: Citation }) {
  return (
    <Tooltip
      content={
        <span className="block max-w-xs">
          {c.quote ? `“${c.quote}”` : c.provision}
          {c.kbVersion ? ` · kb ${c.kbVersion}` : ''}
        </span>
      }
    >
      <span className="inline-flex">
        <Badge tone="neutral" icon={<Scale />}>
          {c.provision}
        </Badge>
      </span>
    </Tooltip>
  );
}

export function TraceLink({
  traceId,
  label = 'Langfuse trace',
  className,
}: {
  traceId?: string | null;
  label?: string;
  className?: string;
}) {
  const url = traceUrl(traceId);
  if (!url) return null;
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      onClick={(e) => e.stopPropagation()}
      className={cn('inline-flex items-center gap-1 text-xs text-primary hover:underline', className)}
    >
      <BookMarked className="size-3" />
      {label}
      <ExternalLink className="size-3" />
    </a>
  );
}

export function SubHeading({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-2 mt-5 flex items-center justify-between gap-2 first:mt-0">
      <h4 className="text-xs font-semibold uppercase tracking-wider text-muted">{children}</h4>
      {right}
    </div>
  );
}

export function SimpleTable({
  head,
  rows,
  className,
}: {
  head: ReactNode[];
  rows: ReactNode[][];
  className?: string;
}) {
  return (
    <div className={cn('overflow-x-auto rounded-lg border border-border', className)}>
      <table className="w-full text-left text-sm">
        <thead className="bg-surface-muted text-xs uppercase tracking-wide text-muted">
          <tr>
            {head.map((h, i) => (
              <th key={i} className="px-3 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((r, i) => (
            <tr key={i} className="align-top transition-colors hover:bg-surface-muted/50">
              {r.map((c, j) => (
                <td key={j} className="px-3 py-2">
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
