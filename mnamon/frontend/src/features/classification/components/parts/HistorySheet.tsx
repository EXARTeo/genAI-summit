import { formatDateTime, formatRelative } from '@/shared/lib/format';
import { actorLabel } from '@/shared/lib/labels';
import { cn } from '@/shared/lib/utils';
import { Badge, EmptyState, Sheet, StatusPill, type BadgeTone } from '@/shared/ui';
import { riskLabel, routeLabel } from '../../lib/classification';
import type { Classification } from '../../lib/types';

const ACTION_TONE: Record<string, BadgeTone> = {
  approved: 'success',
  proposed: 'info',
  rejected: 'danger',
  failed: 'danger',
  stale: 'warning',
  superseded: 'neutral',
  created: 'neutral',
};

/** Every run of the system (newest first) with its append-only event log. */
export function HistorySheet({
  open,
  onOpenChange,
  runs,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  runs: Classification[];
}) {
  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      title="Classification history"
      description="Append-only: proposals are never edited; a re-run is a new row."
    >
      {runs.length === 0 ? (
        <EmptyState compact title="No runs yet" />
      ) : (
        <ol className="space-y-3">
          {runs.map((c) => {
            const r = c.result;
            const risk = r ? riskLabel(r.risk_class) : null;
            return (
              <li key={c.id} className="rounded-lg border border-border p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-mono text-xs [overflow-wrap:anywhere]">{c.id}</span>
                  <StatusPill status={c.status} />
                </div>
                {r && risk && (
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
                    <Badge tone={risk.tone}>{risk.label}</Badge>
                    <span className="text-muted">{routeLabel(r.route, r.art6_3?.condition)}</span>
                  </div>
                )}
                {c.error && <p className="mt-2 text-xs text-danger">{c.error}</p>}
                <ul className="mt-3 space-y-1.5 border-t border-border pt-3">
                  {c.events.map((e) => (
                    <li key={e.id} className="flex items-start gap-2 text-xs">
                      <span
                        className={cn('mt-1 size-1.5 shrink-0 rounded-full bg-current', {
                          'text-success': ACTION_TONE[e.action] === 'success',
                          'text-danger': ACTION_TONE[e.action] === 'danger',
                          'text-warning': ACTION_TONE[e.action] === 'warning',
                          'text-info': ACTION_TONE[e.action] === 'info',
                          'text-muted': !ACTION_TONE[e.action] || ACTION_TONE[e.action] === 'neutral',
                        })}
                        aria-hidden
                      />
                      <div className="min-w-0 flex-1">
                        <span className="font-medium capitalize">{e.action}</span>
                        <span className="text-muted"> · {actorLabel(e.actor)}</span>
                        {e.reason && <p className="mt-0.5 text-muted">“{e.reason}”</p>}
                      </div>
                      <time dateTime={e.at} title={formatDateTime(e.at)} className="num shrink-0 text-muted">
                        {formatRelative(e.at)}
                      </time>
                    </li>
                  ))}
                  {c.events.length === 0 && (
                    <li className="text-xs text-muted">Started {formatRelative(c.createdAt)}</li>
                  )}
                </ul>
              </li>
            );
          })}
        </ol>
      )}
    </Sheet>
  );
}
