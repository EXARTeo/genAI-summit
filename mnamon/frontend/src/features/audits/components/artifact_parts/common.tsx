import { BookMarked, ExternalLink, Scale } from 'lucide-react';
import type { ReactNode } from 'react';
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
          'inline-flex h-5 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-2 text-2xs font-medium',
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

/** "–" for a missing value. */
export const DASH = '–';
export function dash(v: string | number | null | undefined): string | number {
  return v == null || v === '' ? DASH : v;
}

export function ConfidenceBar({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-xs text-muted">confidence {DASH}</span>;
  const tone: Tone = value >= 0.8 ? 'success' : value >= 0.55 ? 'warning' : 'danger';
  return (
    <div className="flex items-center gap-2 text-xs text-muted">
      <div className="h-1 w-16 overflow-hidden rounded-full bg-surface-muted">
        <div
          className={cn('h-full rounded-full transition-[width] duration-700', TONE_CLASSES[tone].bg)}
          style={{ width: `${Math.round(value * 100)}%` }}
        />
      </div>
      <span className="num">
        {Math.round(value * 100)}% · {confidenceLabel(value)}
      </span>
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
          {c.kbVersion && <span className="font-mono text-muted"> · kb {c.kbVersion}</span>}
        </Badge>
      </span>
    </Tooltip>
  );
}

export function TraceLink({
  traceId,
  label = 'Langfuse trace',
  className,
  variant = 'link',
}: {
  traceId?: string | null;
  label?: string;
  className?: string;
  /** `button`: a secondary button (page headers); `link`: inline text link. */
  variant?: 'link' | 'button';
}) {
  const url = traceUrl(traceId);
  if (!url) return null;
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      onClick={(e) => e.stopPropagation()}
      className={cn(
        variant === 'button'
          ? 'inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-surface px-3 text-sm font-medium text-text shadow-card transition-colors hover:bg-surface-muted [&_svg]:size-3.5'
          : 'inline-flex items-center gap-1 text-xs text-muted transition-colors hover:text-primary [&_svg]:size-3',
        className,
      )}
    >
      <BookMarked className={variant === 'button' ? 'text-muted' : ''} />
      {label}
      <ExternalLink className="opacity-60" />
    </a>
  );
}

export function SubHeading({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-2 mt-6 flex items-center justify-between gap-2 first:mt-0">
      <h4 className="text-xs font-semibold text-text/80">{children}</h4>
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
        <thead className="border-b border-border bg-surface-muted/50 text-xs text-muted">
          <tr>
            {head.map((h, i) => (
              <th key={i} className="whitespace-nowrap px-3 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((r, i) => (
            <tr key={i} className="align-top transition-colors hover:bg-surface-muted/40">
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
