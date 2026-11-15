// Built here (no prebuilt fits): a proportional verdict bar + stat tiles that double as the verdict filter.
import { Lock } from 'lucide-react';
import { cn } from '@/shared/lib/utils';
import { Card, Tooltip } from '@/shared/ui';
import { shortHash, type SealedFinding } from '../../lib/findings';
import { TONE_CLASSES, verdictStyle } from '../../lib/styling';

/** Tile wording per verdict: a short name and what it asks of the reader. */
const TILE_TEXT: Record<string, { label: string; hint: string }> = {
  gap: { label: 'Gap', hint: 'Needs action' },
  partial: { label: 'Partial', hint: 'Some subgroups fail' },
  inconclusive: { label: 'Inconclusive', hint: 'Needs a human' },
  pass: { label: 'Pass', hint: 'Meets the threshold' },
  not_assessable_by_testing: { label: 'Not assessable', hint: 'Document review' },
  not_applicable: { label: 'Not applicable', hint: 'Does not apply' },
};

function tileText(v: string) {
  return TILE_TEXT[v] ?? { label: verdictStyle(v).short, hint: '' };
}

export function FindingsSummary({
  rows,
  counts,
  selected,
  onToggle,
}: {
  rows: SealedFinding[];
  counts: { verdict: string; count: number }[];
  selected: string[];
  onToggle: (verdict: string) => void;
}) {
  const total = rows.length;
  const sealed = rows.filter((r) => r.sealed);
  const last = [...sealed].sort((a, b) => a.created_at.localeCompare(b.created_at)).at(-1);
  const kb = rows.find((r) => r.kb_version)?.kb_version;
  const dimmed = (v: string) => selected.length > 0 && !selected.includes(v);

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 pt-4 text-xs text-muted sm:px-5">
        <span className="inline-flex items-center gap-1.5 font-medium text-text">
          <Lock className="size-3.5 text-primary" />
          {sealed.length > 0 ? (
            <>
              <span className="num">{sealed.length}</span> sealed findings
            </>
          ) : (
            <>
              <span className="num">{total}</span> findings (older audit, not sealed)
            </>
          )}
        </span>
        {last && (
          <Tooltip content={`Last link of the hash chain: ${last.hash}`}>
            <span className="num font-mono">chain {shortHash(last.hash, 8)}</span>
          </Tooltip>
        )}
        {kb && <span className="num font-mono">kb {kb}</span>}
        <span className="basis-full sm:ml-auto sm:basis-auto">
          {sealed.length > 0 ? 'Verdicts never change; annotate to contest or accept a risk.' : ''}
        </span>
      </div>

      <div className="px-4 pt-4 sm:px-5">
        <div className="flex h-2.5 gap-0.5 overflow-hidden rounded-full" role="presentation">
          {counts.map(({ verdict, count }) => (
            <button
              key={verdict}
              type="button"
              tabIndex={-1}
              aria-hidden
              onClick={() => onToggle(verdict)}
              style={{ flexGrow: count }}
              className={cn(
                'h-full basis-0 transition-opacity first:rounded-l-full last:rounded-r-full',
                TONE_CLASSES[verdictStyle(verdict).tone].bg,
                dimmed(verdict) && 'opacity-25',
              )}
            />
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-px p-2 sm:grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] sm:p-3">
        {counts.map(({ verdict, count }) => {
          const tone = verdictStyle(verdict).tone;
          const t = tileText(verdict);
          const on = selected.includes(verdict);
          return (
            <button
              key={verdict}
              type="button"
              aria-pressed={on}
              onClick={() => onToggle(verdict)}
              title={verdictStyle(verdict).description}
              className={cn(
                'group rounded-lg px-3 py-2.5 text-left transition-[background-color,opacity] hover:bg-hover',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40',
                on && 'bg-hover-strong',
                dimmed(verdict) && 'opacity-50 hover:opacity-100',
              )}
            >
              <div className="flex items-baseline gap-2">
                <span className="num font-heading text-3xl font-semibold leading-none text-text">
                  {count}
                </span>
                <span className="num text-2xs text-muted">{Math.round((count / total) * 100)}%</span>
              </div>
              <div className="mt-1.5 flex items-center gap-1.5 text-sm font-medium">
                <span className={cn('size-2 shrink-0 rounded-full', TONE_CLASSES[tone].dot)} />
                <span className="truncate">{t.label}</span>
              </div>
              {t.hint && <div className="mt-0.5 truncate pl-3.5 text-2xs text-muted">{t.hint}</div>}
            </button>
          );
        })}
      </div>
    </Card>
  );
}
