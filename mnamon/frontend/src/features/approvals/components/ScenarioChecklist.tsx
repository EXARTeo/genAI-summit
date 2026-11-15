import { useId } from 'react';
import { ReviewBadge, reviewerLabel } from '@/features/audits/components/artifact_parts/PlanViews';
import type { Scenario } from '@/features/audits/lib/types';
import { cn } from '@/shared/lib/utils';
import { Badge, Button, Input } from '@/shared/ui';
import { DEFAULT_EXCLUDE_REASON } from '../lib/approvals';

export interface ScenarioChecklistProps {
  scenarios: Scenario[];
  selected: string[];
  onSelectedChange: (ids: string[]) => void;
  reasons: Record<string, string>;
  onReasonChange: (id: string, reason: string) => void;
}

/**
 * The scenarios gate's selection: approve some scenarios and leave the rest out with a reason.
 * Scenarios the judge reviewed as not relevant start unchecked.
 */
export function ScenarioChecklist({
  scenarios,
  selected,
  onSelectedChange,
  reasons,
  onReasonChange,
}: ScenarioChecklistProps) {
  const headingId = useId();
  const on = new Set(selected);
  const n = scenarios.filter((s) => on.has(s.id)).length;
  const toggle = (id: string, checked: boolean) =>
    onSelectedChange(scenarios.map((s) => s.id).filter((x) => (x === id ? checked : on.has(x))));

  return (
    <section aria-labelledby={headingId} className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h4 id={headingId} className="text-sm font-medium">
            Scenarios to run
          </h4>
          <p className="num text-xs text-muted" aria-live="polite">
            <span className={cn('font-semibold', n === 0 ? 'text-danger' : 'text-text')}>{n}</span> of{' '}
            {scenarios.length} scenarios approved
          </p>
        </div>
        <div className="flex gap-1">
          <Button
            size="sm"
            variant="ghost"
            disabled={n === scenarios.length}
            onClick={() => onSelectedChange(scenarios.map((s) => s.id))}
          >
            Select all
          </Button>
          <Button size="sm" variant="ghost" disabled={n === 0} onClick={() => onSelectedChange([])}>
            None
          </Button>
        </div>
      </div>
      <ul className="space-y-1.5">
        {scenarios.map((s) => {
          const checked = on.has(s.id);
          const flagged = s.review?.verdict === 'not_relevant';
          const reasonId = `${headingId}-${s.id}-why`;
          return (
            <li
              key={s.id}
              className={cn(
                'rounded-lg border p-3 transition-colors duration-150',
                checked ? 'border-border' : 'border-dashed border-border bg-surface-muted/50',
              )}
            >
              <label className="flex cursor-pointer items-start gap-3">
                <input
                  type="checkbox"
                  className="mt-0.5 size-4 shrink-0 cursor-pointer rounded accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                  checked={checked}
                  onChange={(e) => toggle(s.id, e.target.checked)}
                />
                <span className="min-w-0 flex-1 space-y-1">
                  <span className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-mono text-xs text-muted">{s.id}</span>
                    <span className={cn('text-sm font-medium', !checked && 'text-muted')}>
                      {s.title ?? s.metric ?? s.template ?? 'Scenario'}
                    </span>
                  </span>
                  <span className="flex flex-wrap items-center gap-1.5">
                    {(s.obligationId ?? s.requirement) && (
                      <Badge className="h-auto max-w-full whitespace-normal py-0.5 font-mono [overflow-wrap:anywhere]">
                        {s.obligationId ?? s.requirement}
                      </Badge>
                    )}
                    {s.metric && s.title && <span className="font-mono text-2xs text-muted">{s.metric}</span>}
                    {s.review && (
                      <span title={`Reviewed by ${reviewerLabel(s.review.model)}`} className="inline-flex">
                        <ReviewBadge review={s.review} compact />
                      </span>
                    )}
                  </span>
                  {flagged && (
                    <span className="block text-2xs text-danger">
                      {s.review!.model === 'iris' ? 'Iris' : reviewerLabel(s.review!.model)} flagged as not
                      relevant{s.review!.rationale ? `: ${s.review!.rationale}` : ''}
                    </span>
                  )}
                  {s.review?.verdict === 'needs_change' && s.review.suggestedChange && (
                    <span className="block text-2xs text-muted">
                      <span className="font-medium text-text">Suggested:</span> {s.review.suggestedChange}
                    </span>
                  )}
                </span>
              </label>
              {!checked && (
                <div className="mt-2 pl-7">
                  <label htmlFor={reasonId} className="sr-only">
                    Why exclude {s.id}?
                  </label>
                  <Input
                    id={reasonId}
                    className="h-7 text-xs"
                    value={reasons[s.id] ?? ''}
                    onChange={(e) => onReasonChange(s.id, e.target.value)}
                    placeholder={`Why exclude? (optional, default: ${DEFAULT_EXCLUDE_REASON})`}
                    maxLength={300}
                  />
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
