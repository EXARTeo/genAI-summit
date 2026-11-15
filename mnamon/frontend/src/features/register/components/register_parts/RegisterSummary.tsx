// Built here (no prebuilt fits): a proportional state bar + stat tiles that double as the state
// filter, the same pattern as the audit Findings summary.
import { cn } from '@/shared/lib/utils';
import { Card } from '@/shared/ui';
import { TONE_CLASSES, type Tone } from '@/features/audits/lib/styling';
import type { RegisterSummary as Summary } from '../../lib/types';

const TILES: { key: string; label: string; hint: string; tone: Tone; pick: (s: Summary) => number }[] = [
  {
    key: 'open',
    label: 'Open gaps',
    hint: 'Open until fixed or closed',
    tone: 'danger',
    pick: (s) => s.open_gaps,
  },
  {
    key: 'needs_review',
    label: 'Needs review',
    hint: 'Inconclusive, needs a person',
    tone: 'warning',
    pick: (s) => s.needs_review,
  },
  {
    key: 'closed',
    label: 'Accepted risks',
    hint: 'Closed with a reason',
    tone: 'info',
    pick: (s) => s.accepted_risks,
  },
  {
    key: 'resolved',
    label: 'Resolved',
    hint: 'Fixed in a later audit',
    tone: 'success',
    pick: (s) => s.resolved,
  },
  {
    key: 'monitoring',
    label: 'Monitoring',
    hint: 'No gap so far',
    tone: 'neutral',
    pick: (s) => s.monitoring,
  },
];

export function RegisterSummary({
  summary,
  selected,
  onToggle,
}: {
  summary: Summary;
  selected: string[];
  onToggle: (state: string) => void;
}) {
  const tiles = TILES.filter((t) => t.key !== 'monitoring' || t.pick(summary) > 0);
  return (
    <Card className="overflow-hidden">
      <div className="flex h-1.5 gap-0.5 overflow-hidden" aria-hidden>
        {tiles.map((t) => (
          <span
            key={t.key}
            style={{ flexGrow: t.pick(summary) }}
            className={cn(
              'h-full basis-0 transition-opacity',
              TONE_CLASSES[t.tone].bg,
              selected.length > 0 && !selected.includes(t.key) && 'opacity-25',
            )}
          />
        ))}
      </div>
      <div
        className={cn(
          'grid grid-cols-2 gap-px bg-border',
          tiles.length > 4 ? 'sm:grid-cols-3 lg:grid-cols-5' : 'sm:grid-cols-4',
        )}
      >
        {tiles.map((t) => {
          const n = t.pick(summary);
          const on = selected.includes(t.key);
          return (
            <button
              key={t.key}
              type="button"
              aria-pressed={on}
              onClick={() => onToggle(t.key)}
              className={cn(
                'flex flex-col items-start gap-0.5 bg-surface px-4 py-3 text-left transition-colors hover:bg-hover',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
                on && 'bg-hover-strong',
              )}
            >
              <span className="flex items-center gap-1.5 text-xs font-medium text-muted">
                <span className={cn('size-1.5 rounded-full', TONE_CLASSES[t.tone].dot)} />
                {t.label}
              </span>
              <span
                className={cn('num text-2xl font-semibold', n > 0 ? TONE_CLASSES[t.tone].text : 'text-muted')}
              >
                {n}
              </span>
              <span className="text-2xs text-muted">{t.hint}</span>
            </button>
          );
        })}
      </div>
    </Card>
  );
}
