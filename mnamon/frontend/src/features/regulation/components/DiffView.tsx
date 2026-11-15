// Git-style diff table (unified or split) with line numbers and word-level marks. Written here: the
// shared CodeBlock is a highlighter without diff gutters, and no shadcn/AI Elements diff fits our
// wrapped legal prose (long lines must wrap, never scroll sideways).
import { cn } from '@/shared/lib/utils';
import { toSplit } from '../lib/diff';
import type { DiffRow } from '../lib/types';

export type DiffMode = 'unified' | 'split';

const ROW_BG: Record<DiffRow['type'], string> = {
  add: 'bg-success/[0.08]',
  del: 'bg-danger/[0.08]',
  ctx: '',
  hunk: 'bg-info/[0.07]',
};
const GUTTER_BG: Record<DiffRow['type'], string> = {
  add: 'bg-success/15 text-success',
  del: 'bg-danger/15 text-danger',
  ctx: 'text-muted/70',
  hunk: 'text-info',
};

function Words({ row }: { row: DiffRow }) {
  if (!row.words) return <>{row.text || ' '}</>;
  return (
    <>
      {row.words.map((w, i) =>
        w.changed ? (
          <mark
            key={i}
            className={cn(
              'rounded-sm px-px text-inherit',
              row.type === 'add' ? 'bg-success/25' : 'bg-danger/25 line-through decoration-danger/50',
            )}
          >
            {w.text}
          </mark>
        ) : (
          <span key={i}>{w.text}</span>
        ),
      )}
    </>
  );
}

const sign = (t: DiffRow['type']) => (t === 'add' ? '+' : t === 'del' ? '−' : ' ');

function Cell({ row, side }: { row: DiffRow | null; side?: 'old' | 'new' }) {
  if (!row) return <div className="col-span-3 bg-surface-sunken/60" />;
  const no = side === 'old' ? row.oldNo : side === 'new' ? row.newNo : undefined;
  return (
    <>
      <span className={cn('select-none px-2 text-right tabular-nums', GUTTER_BG[row.type])}>{no ?? ''}</span>
      <span className={cn('select-none text-center', GUTTER_BG[row.type])}>{sign(row.type)}</span>
      <span className={cn('min-w-0 whitespace-pre-wrap break-words py-px pl-2 pr-3', ROW_BG[row.type])}>
        <Words row={row} />
      </span>
    </>
  );
}

export function DiffView({ rows, mode = 'unified' }: { rows: DiffRow[]; mode?: DiffMode }) {
  if (mode === 'split') {
    return (
      <div className="grid grid-cols-[2.75rem_1rem_minmax(0,1fr)_2.75rem_1rem_minmax(0,1fr)] font-mono text-xs leading-5">
        {toSplit(rows).map((r, i) =>
          'hunk' in r ? (
            <div key={i} className="col-span-6 border-y border-border/60 bg-info/[0.07] px-3 py-1 text-info">
              {r.hunk.text}
            </div>
          ) : (
            <div key={i} className="contents">
              <Cell row={r.left} side="old" />
              <Cell row={r.right} side="new" />
            </div>
          ),
        )}
      </div>
    );
  }
  return (
    <div className="grid grid-cols-[2.75rem_2.75rem_1rem_minmax(0,1fr)] font-mono text-xs leading-5">
      {rows.map((r, i) =>
        r.type === 'hunk' ? (
          <div key={i} className="col-span-4 border-y border-border/60 bg-info/[0.07] px-3 py-1 text-info">
            {r.text}
          </div>
        ) : (
          <div key={i} className="contents">
            <span className={cn('select-none px-2 text-right tabular-nums', GUTTER_BG[r.type])}>
              {r.oldNo ?? ''}
            </span>
            <Cell row={r} side="new" />
          </div>
        ),
      )}
    </div>
  );
}

/** "+12 −3" with GitHub's five-square bar. */
export function DiffStat({ added, removed }: { added: number; removed: number }) {
  const total = added + removed;
  const green = total === 0 ? 0 : Math.round((added / total) * 5);
  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-2xs tabular-nums">
      <span className="text-success">+{added}</span>
      <span className="text-danger">−{removed}</span>
      <span className="hidden gap-px sm:inline-flex" aria-hidden>
        {Array.from({ length: 5 }, (_, i) => (
          <span
            key={i}
            className={cn(
              'size-2 rounded-[2px]',
              total === 0 ? 'bg-border' : i < green ? 'bg-success' : 'bg-danger',
            )}
          />
        ))}
      </span>
    </span>
  );
}
