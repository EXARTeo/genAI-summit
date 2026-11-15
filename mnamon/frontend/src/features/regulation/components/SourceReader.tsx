import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Fragment } from 'react';
import { formatBytes, formatDateTime } from '@/shared/lib/format';
import { cn } from '@/shared/lib/utils';
import { EmptyState, Markdown, Skeleton } from '@/shared/ui';
import { useDocDiff } from '../hooks/useRegulation';
import { collapseContext, diffCounts, parseUnified } from '../lib/diff';
import { highlightParts, shortSectionLabel } from '../lib/reader';
import type { DocVersion, ReaderBlock, ReaderSection } from '../lib/types';
import { DiffStat, DiffView } from './DiffView';

/** The outline: groups (chapters, annexes, recitals, headings) with their sections. */
export function ReaderOutline({
  sections,
  active,
  onPick,
}: {
  sections: ReaderSection[];
  active: string | undefined;
  onPick: (key: string) => void;
}) {
  if (sections.length === 0) return <p className="px-2 py-3 text-xs text-muted">Nothing matches.</p>;
  return (
    <nav aria-label="Contents" className="min-w-0 overflow-x-hidden text-sm">
      {sections.map((s, i) => {
        const startsGroup = i === 0 || sections[i - 1].group !== s.group;
        return (
          <Fragment key={s.key}>
            {startsGroup && (
              <div className={cn('px-2 pb-1', i > 0 ? 'pt-4' : 'pt-0')}>
                <div className="text-2xs font-semibold uppercase tracking-wider text-muted">{s.group}</div>
                {s.groupSub && <div className="text-2xs text-muted/80">{s.groupSub}</div>}
              </div>
            )}
            <button
              type="button"
              onClick={() => onPick(s.key)}
              aria-current={s.key === active || undefined}
              className={cn(
                'relative flex w-full items-baseline gap-2 rounded-md px-2 py-1 text-left transition-colors',
                s.key === active
                  ? 'bg-primary/10 text-primary'
                  : 'text-text/80 hover:bg-hover hover:text-text',
              )}
            >
              <span
                title={s.title ? undefined : s.label}
                className={cn(
                  'whitespace-nowrap text-xs font-medium tabular-nums',
                  s.title ? 'shrink-0' : 'min-w-0 truncate',
                )}
              >
                {shortSectionLabel(s.label)}
              </span>
              {s.title && <span className="min-w-0 truncate text-xs text-muted">{s.title}</span>}
            </button>
          </Fragment>
        );
      })}
    </nav>
  );
}

function Highlighted({ text, q }: { text: string; q: string }) {
  return (
    <>
      {highlightParts(text, q).map((p, i) =>
        p.hit ? (
          <mark key={i} className="rounded-sm bg-warning/30 px-px text-inherit">
            {p.text}
          </mark>
        ) : (
          <Fragment key={i}>{p.text}</Fragment>
        ),
      )}
    </>
  );
}

function Block({ b, q }: { b: ReaderBlock; q: string }) {
  const body =
    b.markdown && q.trim().length < 2 && b.text.length < 80_000 ? (
      <Markdown className="reader-md">{b.text}</Markdown>
    ) : (
      <p className="whitespace-pre-line">
        <Highlighted text={b.text} q={q} />
      </p>
    );
  return (
    <div
      id={`blk-${b.id}`}
      className="flex scroll-mt-20 gap-3"
      style={{ paddingLeft: `${b.depth * 1.5}rem` }}
    >
      {b.marker && (
        <span className="w-9 shrink-0 text-right font-medium tabular-nums text-muted">{b.marker}</span>
      )}
      <div className="min-w-0 flex-1 [overflow-wrap:anywhere]">{body}</div>
    </div>
  );
}

/** One section typeset for reading: eyebrow label, serif title, numbered blocks. */
export function ReaderSectionView({
  s,
  q,
  compact,
}: {
  s: ReaderSection;
  q: string;
  /** In the full-text flow: smaller headings, no extra top space. */
  compact?: boolean;
}) {
  return (
    <section
      id={`sec-${s.key}`}
      aria-label={s.label}
      className={cn(
        'scroll-mt-20',
        compact && '[contain-intrinsic-size:auto_480px] [content-visibility:auto]',
      )}
    >
      <div className="text-2xs font-semibold uppercase tracking-[0.14em] text-primary">
        {s.group !== s.label && s.group !== 'Document' ? `${s.group} · ` : ''}
        {s.label}
      </div>
      {s.title && (
        <h2
          className={cn(
            'mt-1 font-heading font-medium leading-tight',
            compact ? 'text-2xl' : 'text-3xl sm:text-[34px]',
          )}
        >
          <Highlighted text={s.title} q={q} />
        </h2>
      )}
      <div className="mt-5 space-y-3 text-[15px] leading-7 text-text/90">
        {s.blocks.length === 0 ? (
          <p className="text-sm text-muted">No text in this section.</p>
        ) : (
          s.blocks.map((b) => <Block key={b.id} b={b} q={q} />)
        )}
      </div>
    </section>
  );
}

export function PrevNext({
  prev,
  next,
  onPick,
}: {
  prev?: ReaderSection;
  next?: ReaderSection;
  onPick: (key: string) => void;
}) {
  return (
    <div className="mt-12 grid grid-cols-2 gap-3 border-t border-border pt-4">
      {prev ? (
        <button
          type="button"
          onClick={() => onPick(prev.key)}
          className="group flex min-w-0 flex-col items-start rounded-md p-2 text-left hover:bg-hover"
        >
          <span className="flex items-center gap-1 text-2xs text-muted">
            <ChevronLeft className="size-3" /> Previous
          </span>
          <span className="w-full truncate text-sm font-medium">{prev.label}</span>
        </button>
      ) : (
        <span />
      )}
      {next && (
        <button
          type="button"
          onClick={() => onPick(next.key)}
          className="group flex min-w-0 flex-col items-end rounded-md p-2 text-right hover:bg-hover"
        >
          <span className="flex items-center gap-1 text-2xs text-muted">
            Next <ChevronRight className="size-3" />
          </span>
          <span className="w-full truncate text-sm font-medium">{next.label}</span>
        </button>
      )}
    </div>
  );
}

/** Version history of the source's main document, and the diff of a version to the one before. */
export function ReaderHistory({
  docId,
  versions,
  version,
  onVersion,
}: {
  docId: string;
  versions: DocVersion[];
  version: number;
  onVersion: (v: number) => void;
}) {
  const stored = versions.filter((v) => v.status !== 'failed' && v.status !== 'same');
  const diff = useDocDiff(docId, version - 1, version);
  const rows = diff.data ? parseUnified(diff.data.unified) : null;
  return (
    <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
      <ol className="space-y-1">
        {[...stored].reverse().map((v) => (
          <li key={`${v.version}-${v.fetchedAt}`}>
            <button
              type="button"
              onClick={() => onVersion(v.version)}
              aria-current={v.version === version || undefined}
              className={cn(
                'flex w-full flex-col rounded-md border px-3 py-2 text-left transition-colors',
                v.version === version
                  ? 'border-primary/40 bg-primary/5'
                  : 'border-transparent hover:bg-hover',
              )}
            >
              <span className="flex items-center gap-2 text-sm font-medium">
                v{v.version}
                <span
                  className={cn(
                    'text-2xs font-normal',
                    v.status === 'changed' ? 'text-warning' : 'text-muted',
                  )}
                >
                  {v.status === 'new' ? 'first fetch' : v.status}
                </span>
              </span>
              <span className="text-2xs text-muted">
                {formatDateTime(v.fetchedAt)} · {formatBytes(v.bytes)}
              </span>
            </button>
          </li>
        ))}
      </ol>
      <div className="min-w-0">
        {version <= 1 ? (
          <EmptyState compact title="First version" description="Pick a later version to see what changed." />
        ) : diff.isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : rows && rows.length > 0 ? (
          <div className="overflow-hidden rounded-md border border-border">
            <div className="flex items-center gap-3 border-b border-border bg-surface-sunken/50 px-4 py-2 text-xs">
              <span className="font-mono">
                v{version - 1} → v{version}
              </span>
              <span className="ml-auto">
                <DiffStat {...diffCounts(rows)} />
              </span>
            </div>
            <DiffView rows={collapseContext(rows, 3)} />
          </div>
        ) : (
          <EmptyState
            compact
            title="No text change"
            description="The fetched bytes changed, the extracted text did not."
          />
        )}
      </div>
    </div>
  );
}
